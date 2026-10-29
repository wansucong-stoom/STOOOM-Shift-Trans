#include <windows.h>
#include <msctf.h>
#include <wrl/client.h>
#include <cstdio>
#include <cwchar>
#include "protocol.h"

using Microsoft::WRL::ComPtr;
namespace {
constexpr LANGID Languages[] = {0x0412, 0x0409, 0x0411};
struct ComScope {
    HRESULT result = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    ~ComScope() { if (SUCCEEDED(result)) CoUninitialize(); }
};
void PrintFatal(const char* step, HRESULT hr) {
    std::printf("{\"ok\":false,\"step\":\"%s\",\"hresult\":\"0x%08lX\"}\n", step, static_cast<unsigned long>(hr));
}
}

int wmain(int argc, wchar_t** argv) {
    bool activate = argc == 2 && wcscmp(argv[1], L"--activate") == 0;
    bool statusOnly = argc == 2 && wcscmp(argv[1], L"--status") == 0;
    if (!activate && !statusOnly) {
        std::puts("Usage: STOOMTextServiceHost.exe --activate | --status\n"
                  "--activate enables STOOM's auxiliary profiles for this user/desktop.\n"
                  "It does not change the active input language or default keyboard.\n"
                  "--status performs read-only profile checks.\n"
                  "Profile activation is not proof that a target app exposes a TSF context.");
        return argc == 2 && wcscmp(argv[1], L"--help") == 0 ? 0 : 2;
    }
    ComScope com;
    if (FAILED(com.result)) { PrintFatal("CoInitializeEx", com.result); return 1; }
    ComPtr<ITfInputProcessorProfileMgr> profiles;
    HRESULT hr = CoCreateInstance(CLSID_TF_InputProcessorProfiles, nullptr, CLSCTX_INPROC_SERVER,
                                  IID_PPV_ARGS(&profiles));
    if (FAILED(hr)) { PrintFatal("CoCreateInstance", hr); return 1; }

    // Preflight every language before enabling anything. A missing component
    // remains a setup failure, never silently reported as ready.
    HRESULT preflight[ARRAYSIZE(Languages)]{};
    bool registered = true;
    for (size_t index = 0; index < ARRAYSIZE(Languages); ++index) {
        TF_INPUTPROCESSORPROFILE profile{};
        preflight[index] = profiles->GetProfile(TF_PROFILETYPE_INPUTPROCESSOR, Languages[index],
            stoom::ServiceId, stoom::ProfileId, nullptr, &profile);
        if (preflight[index] == S_OK && !IsEqualGUID(profile.catid, stoom::CategoryId))
            preflight[index] = HRESULT_FROM_WIN32(ERROR_INVALID_DATA);
        if (preflight[index] != S_OK) registered = false;
    }
    bool ok = registered;
    HRESULT results[ARRAYSIZE(Languages)]{};
    for (size_t index = 0; index < ARRAYSIZE(Languages); ++index) {
        results[index] = preflight[index];
        if (activate && registered) {
            results[index] = profiles->ActivateProfile(TF_PROFILETYPE_INPUTPROCESSOR,
                Languages[index], stoom::ServiceId, stoom::ProfileId, nullptr,
                TF_IPPMF_FORSESSION | TF_IPPMF_ENABLEPROFILE | TF_IPPMF_DONTCARECURRENTINPUTLANGUAGE);
            if (results[index] != S_OK) ok = false;
        }
    }
    std::printf("{\"ok\":%s,\"operation\":\"%s\",\"registered\":%s,\"runtime_verified\":false,\"profiles\":[",
        ok ? "true" : "false", activate ? "activate" : "status", registered ? "true" : "false");
    for (size_t index = 0; index < ARRAYSIZE(Languages); ++index)
        std::printf("%s{\"language\":%u,\"hresult\":\"0x%08lX\"}", index ? "," : "",
            static_cast<unsigned>(Languages[index]), static_cast<unsigned long>(results[index]));
    std::puts("]}");
    return ok ? 0 : 1;
}
