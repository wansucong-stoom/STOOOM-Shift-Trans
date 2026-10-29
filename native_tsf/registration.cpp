#include <windows.h>
#include <msctf.h>
#include <wrl/client.h>
#include <array>
#include <string>
#include <vector>
#include "protocol.h"

extern HINSTANCE g_module;

namespace {
using Microsoft::WRL::ComPtr;
constexpr LANGID Languages[] = {0x0412, 0x0409, 0x0411};
constexpr wchar_t Description[] = L"STOOM Translation Text Service";

struct ComScope {
    HRESULT result = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    ~ComScope() { if (SUCCEEDED(result)) CoUninitialize(); }
    bool usable() const { return SUCCEEDED(result) || result == RPC_E_CHANGED_MODE; }
};

std::wstring ClassKey() {
    wchar_t guid[40]{};
    StringFromGUID2(stoom::ServiceId, guid, ARRAYSIZE(guid));
    return std::wstring(L"Software\\Classes\\CLSID\\") + guid;
}

// Save only the values we own, so an upgrade failure restores the previous
// COM DLL path without deleting an existing installation's other values.
struct SavedValue {
    HKEY key{};
    const wchar_t* name{};
    bool present{}, changed{};
    DWORD type{};
    std::vector<BYTE> data;
    HRESULT save(HKEY target, const wchar_t* valueName) {
        key = target;
        name = valueName;
        DWORD size = 0;
        LSTATUS status = RegQueryValueExW(key, name, nullptr, &type, nullptr, &size);
        if (status == ERROR_FILE_NOT_FOUND) return S_OK;
        if (status != ERROR_SUCCESS) return HRESULT_FROM_WIN32(status);
        present = true;
        data.resize(size);
        status = RegQueryValueExW(key, name, nullptr, &type, data.data(), &size);
        return HRESULT_FROM_WIN32(status);
    }
    HRESULT set(const wchar_t* text) {
        LSTATUS status = RegSetValueExW(key, name, 0, REG_SZ,
            reinterpret_cast<const BYTE*>(text),
            static_cast<DWORD>((wcslen(text) + 1) * sizeof(wchar_t)));
        if (status == ERROR_SUCCESS) changed = true;
        return HRESULT_FROM_WIN32(status);
    }
    void restore() const {
        if (!changed) return;
        if (present) RegSetValueExW(key, name, 0, type, data.data(), static_cast<DWORD>(data.size()));
        else RegDeleteValueW(key, name);
    }
};

struct ComRegistration {
    std::wstring path = ClassKey();
    HKEY clsid{}, server{};
    DWORD classDisposition{}, serverDisposition{};
    std::array<SavedValue, 3> saved;
    bool committed{};
    ~ComRegistration() {
        if (!committed) for (const auto& value : saved) value.restore();
        if (server) RegCloseKey(server);
        if (clsid) RegCloseKey(clsid);
        if (!committed) {
            if (classDisposition == REG_CREATED_NEW_KEY) RegDeleteTreeW(HKEY_LOCAL_MACHINE, path.c_str());
            else if (serverDisposition == REG_CREATED_NEW_KEY)
                RegDeleteTreeW(HKEY_LOCAL_MACHINE, (path + L"\\InprocServer32").c_str());
        }
    }
    HRESULT write(const wchar_t* module) {
        LSTATUS status = RegCreateKeyExW(HKEY_LOCAL_MACHINE, path.c_str(), 0, nullptr,
            REG_OPTION_NON_VOLATILE, KEY_READ | KEY_WRITE, nullptr, &clsid, &classDisposition);
        if (status != ERROR_SUCCESS) return HRESULT_FROM_WIN32(status);
        status = RegCreateKeyExW(clsid, L"InprocServer32", 0, nullptr,
            REG_OPTION_NON_VOLATILE, KEY_READ | KEY_WRITE, nullptr, &server, &serverDisposition);
        if (status != ERROR_SUCCESS) return HRESULT_FROM_WIN32(status);
        HRESULT hr = saved[0].save(clsid, nullptr);
        if (SUCCEEDED(hr)) hr = saved[1].save(server, nullptr);
        if (SUCCEEDED(hr)) hr = saved[2].save(server, L"ThreadingModel");
        if (SUCCEEDED(hr)) hr = saved[0].set(Description);
        if (SUCCEEDED(hr)) hr = saved[1].set(module);
        if (SUCCEEDED(hr)) hr = saved[2].set(L"Apartment");
        return hr;
    }
};

HRESULT CategoryPresent(ITfCategoryMgr* categories, REFGUID category, REFGUID item, bool& present) {
    present = false;
    ComPtr<IEnumGUID> enumeration;
    HRESULT hr = categories->EnumItemsInCategory(category, &enumeration);
    if (FAILED(hr)) return hr;
    if (!enumeration) return E_UNEXPECTED;
    GUID value{};
    ULONG fetched = 0;
    while ((hr = enumeration->Next(1, &value, &fetched)) == S_OK && fetched == 1) {
        if (IsEqualGUID(value, item)) { present = true; return S_OK; }
    }
    return FAILED(hr) ? hr : S_OK;
}

HRESULT RegisterService() {
    ComScope com;
    if (!com.usable()) return com.result;
    wchar_t module[32768]{};
    DWORD length = GetModuleFileNameW(g_module, module, ARRAYSIZE(module));
    if (!length || length >= ARRAYSIZE(module)) return HRESULT_FROM_WIN32(ERROR_BAD_PATHNAME);
    ComPtr<ITfInputProcessorProfileMgr> profiles;
    ComPtr<ITfCategoryMgr> categories;
    HRESULT hr = CoCreateInstance(CLSID_TF_InputProcessorProfiles, nullptr, CLSCTX_INPROC_SERVER,
                                 IID_PPV_ARGS(&profiles));
    if (FAILED(hr)) return hr;
    hr = CoCreateInstance(CLSID_TF_CategoryMgr, nullptr, CLSCTX_INPROC_SERVER,
                          IID_PPV_ARGS(&categories));
    if (FAILED(hr)) return hr;

    bool categoryExisted = false, memberExisted = false;
    hr = CategoryPresent(categories.Get(), GUID_TFCAT_CATEGORY_OF_TIP, stoom::CategoryId, categoryExisted);
    if (SUCCEEDED(hr)) hr = CategoryPresent(categories.Get(), stoom::CategoryId, stoom::ServiceId, memberExisted);
    if (FAILED(hr)) return hr;
    bool profileExisted[ARRAYSIZE(Languages)]{};
    for (size_t index = 0; index < ARRAYSIZE(Languages); ++index) {
        TF_INPUTPROCESSORPROFILE existing{};
        hr = profiles->GetProfile(TF_PROFILETYPE_INPUTPROCESSOR, Languages[index], stoom::ServiceId,
                                  stoom::ProfileId, nullptr, &existing);
        profileExisted[index] = hr == S_OK;
    }

    ComRegistration registration;
    hr = registration.write(module);
    if (FAILED(hr)) return hr;
    bool categoryAdded = false, memberAdded = false;
    bool profileAdded[ARRAYSIZE(Languages)]{};
    hr = S_OK;
    if (!categoryExisted) {
        hr = categories->RegisterCategory(stoom::ServiceId, GUID_TFCAT_CATEGORY_OF_TIP, stoom::CategoryId);
        categoryAdded = SUCCEEDED(hr);
    }
    if (SUCCEEDED(hr) && !memberExisted) {
        hr = categories->RegisterCategory(stoom::ServiceId, stoom::CategoryId, stoom::ServiceId);
        memberAdded = SUCCEEDED(hr);
    }
    for (size_t index = 0; SUCCEEDED(hr) && index < ARRAYSIZE(Languages); ++index) {
        if (profileExisted[index]) continue;
        // Disabled by default: the unelevated tray enables only the current
        // user's profiles. No keyboard substitution or default-IME changes.
        hr = profiles->RegisterProfile(stoom::ServiceId, Languages[index], stoom::ProfileId,
            Description, ARRAYSIZE(Description) - 1, module, length, 0,
            nullptr, 0, FALSE, 0);
        profileAdded[index] = SUCCEEDED(hr);
    }
    if (FAILED(hr)) {
        for (size_t index = 0; index < ARRAYSIZE(Languages); ++index)
            if (profileAdded[index]) profiles->UnregisterProfile(stoom::ServiceId, Languages[index], stoom::ProfileId, 0);
        if (memberAdded) categories->UnregisterCategory(stoom::ServiceId, stoom::CategoryId, stoom::ServiceId);
        if (categoryAdded) categories->UnregisterCategory(stoom::ServiceId, GUID_TFCAT_CATEGORY_OF_TIP, stoom::CategoryId);
        return hr;
    }
    registration.committed = true;
    return S_OK;
}

HRESULT UnregisterService() {
    ComScope com;
    if (!com.usable()) return com.result;
    // An older version's uninstall log must not unregister a newer DLL.
    wchar_t module[32768]{}, registered[32768]{};
    DWORD bytes=sizeof(registered);
    if(!GetModuleFileNameW(g_module,module,ARRAYSIZE(module)))return HRESULT_FROM_WIN32(GetLastError());
    const LSTATUS owner=RegGetValueW(HKEY_LOCAL_MACHINE,(ClassKey()+L"\\InprocServer32").c_str(),nullptr,RRF_RT_REG_SZ,nullptr,registered,&bytes);
    if(owner==ERROR_FILE_NOT_FOUND||owner==ERROR_PATH_NOT_FOUND)return S_OK;
    if(owner!=ERROR_SUCCESS)return HRESULT_FROM_WIN32(owner);
    if(_wcsicmp(module,registered)!=0)return S_OK;
    ComPtr<ITfInputProcessorProfileMgr> profiles;
    ComPtr<ITfCategoryMgr> categories;
    HRESULT result = S_OK;
    auto keepFailure = [&result](HRESULT hr) { if (FAILED(hr) && SUCCEEDED(result)) result = hr; };
    HRESULT hr = CoCreateInstance(CLSID_TF_InputProcessorProfiles, nullptr, CLSCTX_INPROC_SERVER,
                                 IID_PPV_ARGS(&profiles));
    keepFailure(hr);
    if (profiles) {
        for (LANGID language : Languages) {
            // Only this service/profile is removed. No default-input or other
            // IME registry keys are changed during uninstall.
            keepFailure(profiles->UnregisterProfile(stoom::ServiceId, language, stoom::ProfileId, 0));
        }
    }
    hr = CoCreateInstance(CLSID_TF_CategoryMgr, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&categories));
    keepFailure(hr);
    if (categories) {
        keepFailure(categories->UnregisterCategory(stoom::ServiceId, stoom::CategoryId, stoom::ServiceId));
        keepFailure(categories->UnregisterCategory(stoom::ServiceId, GUID_TFCAT_CATEGORY_OF_TIP, stoom::CategoryId));
    }
    const LSTATUS status = RegDeleteTreeW(HKEY_LOCAL_MACHINE, ClassKey().c_str());
    if (status != ERROR_FILE_NOT_FOUND && status != ERROR_PATH_NOT_FOUND)
        keepFailure(HRESULT_FROM_WIN32(status));
    return result;
}
}

extern "C" HRESULT __declspec(dllexport) WINAPI DllRegisterServer() {
    try { return RegisterService(); }
    catch (...) { return E_OUTOFMEMORY; }
}

extern "C" HRESULT __declspec(dllexport) WINAPI DllUnregisterServer() {
    try { return UnregisterService(); }
    catch (...) { return E_OUTOFMEMORY; }
}
