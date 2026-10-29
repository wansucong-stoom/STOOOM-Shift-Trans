#include <windows.h>
#include <msctf.h>
#include <wrl/client.h>
#include <cstdio>
#include <cwchar>
#include <string>
#include "protocol.h"
using Microsoft::WRL::ComPtr;
namespace {
constexpr LANGID Languages[] = {0x0412, 0x0409, 0x0411};
struct ComScope {
    HRESULT result = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    ~ComScope() { if (SUCCEEDED(result)) CoUninitialize(); }
};
struct PrivateManager {
    ComPtr<ITfThreadMgrEx> value;
    TfClientId client = TF_CLIENTID_NULL;
    ~PrivateManager() { if (value && client != TF_CLIENTID_NULL) value->Deactivate(); }
};
void Fatal(const char* step, HRESULT hr) {
    std::printf("{\"ok\":false,\"step\":\"%s\",\"hresult\":\"0x%08lX\",\"self_service_loaded\":false,\"runtime_verified\":false}\n",
        step, static_cast<unsigned long>(hr));
}
std::string GuidText(REFGUID id) {
    wchar_t wide[40]{}; StringFromGUID2(id, wide, ARRAYSIZE(wide));
    std::string result;
    for (wchar_t c : wide) { if (!c) break; result.push_back(static_cast<char>(c)); }
    return result;
}
HRESULT Contains(ITfCategoryMgr* categories, REFGUID category, REFGUID wanted, bool& found) {
    found = false; ComPtr<IEnumGUID> values;
    HRESULT hr = categories->EnumItemsInCategory(category, &values);
    if (FAILED(hr)) return hr;
    if (!values) return E_UNEXPECTED;
    GUID value{}; ULONG count = 0;
    while ((hr = values->Next(1, &value, &count)) == S_OK && count == 1) {
        if (value == wanted) { found = true; return S_OK; }
    }
    return FAILED(hr) ? hr : S_OK;
}
bool SameKeyboard(const TF_INPUTPROCESSORPROFILE& a, const TF_INPUTPROCESSORPROFILE& b) {
    return a.dwProfileType == b.dwProfileType && a.langid == b.langid &&
        a.clsid == b.clsid && a.guidProfile == b.guidProfile && a.hkl == b.hkl;
}
bool ServiceWindowExists() {
    wchar_t title[80];
    swprintf_s(title, L"STOOM.TSF.%lu.%lu", GetCurrentProcessId(), GetCurrentThreadId());
    HWND window = nullptr;
    while ((window = FindWindowExW(HWND_MESSAGE, window, nullptr, title)) != nullptr) {
        DWORD process = 0; DWORD thread = GetWindowThreadProcessId(window, &process);
        wchar_t name[256]{};
        if (process != GetCurrentProcessId() || thread != GetCurrentThreadId() ||
            GetClassNameW(window, name, ARRAYSIZE(name)) == 0) continue;
        const size_t prefix = wcslen(stoom::WindowClass);
        if (wcsncmp(name, stoom::WindowClass, prefix) == 0 &&
            (name[prefix] == 0 || name[prefix] == L'.')) return true;
    }
    return false;
}
HRESULT SelfProbe(PrivateManager& manager, bool& loaded) {
    loaded = false;
    HRESULT hr = CoCreateInstance(CLSID_TF_ThreadMgr, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&manager.value));
    if (FAILED(hr)) return hr;
    // The profile must be active BEFORE this manager is initialized. A real
    // process-only probe showed that the reverse order can update the active
    // catalog without loading the service DLL in the already initialized thread.
    hr = manager.value->ActivateEx(&manager.client, TF_TMAE_NOACTIVATEKEYBOARDLAYOUT);
    if (FAILED(hr)) return hr;
    const ULONGLONG deadline = GetTickCount64() + 1500;
    do {
        MSG message{};
        while (PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE)) {
            TranslateMessage(&message); DispatchMessageW(&message);
        }
        loaded = ServiceWindowExists();
        if (loaded) return S_OK;
        MsgWaitForMultipleObjects(0, nullptr, FALSE, 10, QS_ALLINPUT);
    } while (GetTickCount64() < deadline);
    return HRESULT_FROM_WIN32(ERROR_TIMEOUT);
}
}
int wmain(int argc, wchar_t** argv) {
    const bool activate = argc == 2 && wcscmp(argv[1], L"--activate") == 0;
    const bool statusOnly = argc == 2 && wcscmp(argv[1], L"--status") == 0;
    if (!activate && !statusOnly) {
        std::puts("Usage: STOOMTextServiceHost.exe --activate | --status\n"
            "--activate enables STOOM auxiliary profiles for this user/desktop,\n"
            "then verifies a service window in this helper process.\n"
            "It does not change the input language or default keyboard.\n"
            "--status only reads profiles and explicit category registration.\n"
            "Self activation does not verify the user's target editor.");
        return argc == 2 && wcscmp(argv[1], L"--help") == 0 ? 0 : 2;
    }
    ComScope com;
    if (FAILED(com.result)) { Fatal("CoInitializeEx", com.result); return 1; }
    ComPtr<ITfInputProcessorProfileMgr> profiles;
    ComPtr<ITfInputProcessorProfiles> legacy;
    ComPtr<ITfCategoryMgr> categories;
    HRESULT hr = CoCreateInstance(CLSID_TF_InputProcessorProfiles, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&profiles));
    if (FAILED(hr)) { Fatal("CoCreateInstance", hr); return 1; }
    hr = profiles.As(&legacy);
    if (FAILED(hr)) { Fatal("ITfInputProcessorProfiles", hr); return 1; }
    hr = CoCreateInstance(CLSID_TF_CategoryMgr, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&categories));
    if (FAILED(hr)) { Fatal("ITfCategoryMgr", hr); return 1; }

    // Actual Windows readback reports GUID_NULL catid for this correctly
    // registered, loadable auxiliary service. Verify explicit relations instead.
    bool categoryType = false, serviceMember = false, keyboardMember = false;
    HRESULT categoryHr = Contains(categories.Get(), GUID_TFCAT_CATEGORY_OF_TIP, stoom::CategoryId, categoryType);
    if (SUCCEEDED(categoryHr)) categoryHr = Contains(categories.Get(), stoom::CategoryId, stoom::ServiceId, serviceMember);
    if (SUCCEEDED(categoryHr)) categoryHr = Contains(categories.Get(), GUID_TFCAT_TIP_KEYBOARD, stoom::ServiceId, keyboardMember);
    const bool auxiliary = categoryHr == S_OK && categoryType && serviceMember && !keyboardMember;
    HRESULT preflight[ARRAYSIZE(Languages)]{};
    TF_INPUTPROCESSORPROFILE details[ARRAYSIZE(Languages)]{};
    BOOL enabled[ARRAYSIZE(Languages)]{};
    bool registered = auxiliary;
    for (size_t i = 0; i < ARRAYSIZE(Languages); ++i) {
        preflight[i] = profiles->GetProfile(TF_PROFILETYPE_INPUTPROCESSOR, Languages[i],
            stoom::ServiceId, stoom::ProfileId, nullptr, &details[i]);
        // Never repair auxiliary activation by stealing the user's keyboard TIP.
        if (preflight[i] == S_OK && (details[i].catid == GUID_TFCAT_TIP_KEYBOARD || !auxiliary))
            preflight[i] = HRESULT_FROM_WIN32(ERROR_INVALID_DATA);
        legacy->IsEnabledLanguageProfile(stoom::ServiceId, Languages[i], stoom::ProfileId, &enabled[i]);
        if (preflight[i] != S_OK) registered = false;
    }
    LANGID currentLanguage = 0;
    HRESULT languageHr = legacy->GetCurrentLanguage(&currentLanguage);
    bool currentSupported = false;
    for (LANGID language : Languages) if (currentLanguage == language) currentSupported = true;
    TF_INPUTPROCESSORPROFILE keyboardBefore{}, keyboardAfter{};
    HRESULT keyboardBeforeHr = profiles->GetActiveProfile(GUID_TFCAT_TIP_KEYBOARD, &keyboardBefore);
    HRESULT keyboardAfterHr = E_PENDING;
    bool keyboardUnchanged = false, selfLoaded = false;
    HRESULT selfHr = E_PENDING;
    bool ok = registered;
    const char* error = registered ? "" : "registration_incomplete";
    const bool canActivate = registered && languageHr == S_OK && currentSupported && keyboardBeforeHr == S_OK;
    if (activate && !canActivate) {
        ok = false;
        if (registered) error = currentSupported ? "keyboard_state_unavailable" : "current_language_not_supported";
    }
    HRESULT results[ARRAYSIZE(Languages)]{};
    for (size_t i = 0; i < ARRAYSIZE(Languages); ++i) {
        results[i] = preflight[i];
        if (activate && canActivate) {
            results[i] = profiles->ActivateProfile(TF_PROFILETYPE_INPUTPROCESSOR, Languages[i],
                stoom::ServiceId, stoom::ProfileId, nullptr,
                TF_IPPMF_FORSESSION | TF_IPPMF_ENABLEPROFILE | TF_IPPMF_DONTCARECURRENTINPUTLANGUAGE);
            if (results[i] != S_OK) { ok = false; error = "profile_activation_failed"; }
        }
    }
    PrivateManager manager;
    if (activate && canActivate && ok) {
        selfHr = SelfProbe(manager, selfLoaded);
        if (selfHr != S_OK || !selfLoaded) { ok = false; error = "self_service_not_loaded"; }
    }
    if (activate && canActivate) {
        keyboardAfterHr = profiles->GetActiveProfile(GUID_TFCAT_TIP_KEYBOARD, &keyboardAfter);
        keyboardUnchanged = keyboardBeforeHr == S_OK && keyboardAfterHr == S_OK && SameKeyboard(keyboardBefore, keyboardAfter);
        if (!keyboardUnchanged) { ok = false; error = "keyboard_profile_changed"; }
    }
    std::printf("{\"ok\":%s,\"operation\":\"%s\",\"registered\":%s,\"self_service_loaded\":%s,\"runtime_verified\":false,"
        "\"error\":\"%s\",\"current_language\":%u,\"keyboard_unchanged\":%s,\"self_probe_hresult\":\"0x%08lX\","
        "\"category_checks\":{\"type_registered\":%s,\"service_member\":%s,\"keyboard_member\":%s,\"hresult\":\"0x%08lX\"},\"profiles\":[",
        ok ? "true" : "false", activate ? "activate" : "status", registered ? "true" : "false", selfLoaded ? "true" : "false",
        error, static_cast<unsigned>(currentLanguage), activate ? (keyboardUnchanged ? "true" : "false") : "null",
        static_cast<unsigned long>(selfHr), categoryType ? "true" : "false", serviceMember ? "true" : "false",
        keyboardMember ? "true" : "false", static_cast<unsigned long>(categoryHr));
    for (size_t i = 0; i < ARRAYSIZE(Languages); ++i)
        std::printf("%s{\"language\":%u,\"hresult\":\"0x%08lX\",\"catid\":\"%s\",\"enabled_before\":%s}", i ? "," : "",
            static_cast<unsigned>(Languages[i]), static_cast<unsigned long>(results[i]),
            GuidText(details[i].catid).c_str(), enabled[i] ? "true" : "false");
    std::puts("]}");
    return ok ? 0 : 1;
}

