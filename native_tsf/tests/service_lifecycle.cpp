// Registration-free lifecycle test of the shipped DLL and the real Windows
// TSF thread manager. No document is created, no app focus is changed, and no
// language profile is registered/enabled/activated globally.
#include <windows.h>
#include <msctf.h>
#include <wrl/client.h>
#include <atomic>
#include <cstdio>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#include "../protocol.h"

using Microsoft::WRL::ComPtr;
namespace {
using GetClassObject = HRESULT (STDAPICALLTYPE*)(REFCLSID, REFIID, void**);
using CanUnloadNow = HRESULT (STDAPICALLTYPE*)();

void Require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
void RequireHr(HRESULT value, const char* message) {
    if (FAILED(value)) {
        char detail[256];
        sprintf_s(detail, "%s (HRESULT 0x%08lX)", message, static_cast<unsigned long>(value));
        throw std::runtime_error(detail);
    }
}

struct ComScope {
    HRESULT result = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    ComScope() { RequireHr(result, "CoInitializeEx"); }
    ~ComScope() { if (SUCCEEDED(result)) CoUninitialize(); }
};

struct ThreadManager {
    ComPtr<ITfThreadMgrEx> value;
    TfClientId client = TF_CLIENTID_NULL;
    ThreadManager() {
        RequireHr(CoCreateInstance(CLSID_TF_ThreadMgr, nullptr, CLSCTX_INPROC_SERVER,
            IID_PPV_ARGS(&value)), "create real TSF thread manager");
        // These documented flags keep this private test process from loading
        // selected TIPs or changing the thread's keyboard layout.
        RequireHr(value->ActivateEx(&client, TF_TMAE_NOACTIVATETIP | TF_TMAE_NOACTIVATEKEYBOARDLAYOUT),
            "activate private TSF thread manager");
    }
    ~ThreadManager() { if (client != TF_CLIENTID_NULL) value->Deactivate(); }
};

struct Service {
    ComPtr<ITfTextInputProcessorEx> value;
    bool active = false;
    explicit Service(GetClassObject getClass) {
        ComPtr<IClassFactory> factory;
        RequireHr(getClass(stoom::ServiceId, IID_PPV_ARGS(&factory)), "DLL class factory");
        RequireHr(factory->CreateInstance(nullptr, IID_PPV_ARGS(&value)), "create DLL service");
    }
    void activate(ThreadManager& manager) {
        RequireHr(value->ActivateEx(manager.value.Get(), manager.client, 0), "activate service directly");
        active = true;
    }
    void deactivate() {
        RequireHr(value->Deactivate(), "deactivate service");
        active = false;
    }
    ~Service() { if (active) value->Deactivate(); }
};

struct Window {
    HWND handle = nullptr;
    std::wstring className;
};

std::vector<Window> OwnedWindows() {
    wchar_t title[80];
    swprintf_s(title, L"STOOM.TSF.%lu.%lu", GetCurrentProcessId(), GetCurrentThreadId());
    std::vector<Window> result;
    HWND current = nullptr;
    while ((current = FindWindowExW(HWND_MESSAGE, current, nullptr, title)) != nullptr) {
        DWORD pid = 0;
        DWORD tid = GetWindowThreadProcessId(current, &pid);
        if (pid != GetCurrentProcessId() || tid != GetCurrentThreadId()) continue;
        wchar_t className[256]{};
        Require(GetClassNameW(current, className, ARRAYSIZE(className)) > 0, "read message-window class");
        Require(wcsncmp(className, stoom::WindowClass, wcslen(stoom::WindowClass)) == 0,
            "message window belongs to the service");
        result.push_back({current, className});
    }
    return result;
}

void RequireRemoved(const Window& old, HMODULE module) {
    Require(!IsWindow(old.handle), "deactivated service left its message window alive");
    WNDCLASSW info{};
    Require(!GetClassInfoW(module, old.className.c_str(), &info),
        "deactivated service left a registered DLL window class");
}

void PairCycle(GetClassObject getClass, HMODULE module, ThreadManager& manager) {
    Require(OwnedWindows().empty(), "unexpected initial test-thread service window");
    Service first(getClass), second(getClass);
    first.activate(manager);
    auto initial = OwnedWindows();
    Require(initial.size() == 1, "first service did not create exactly one message window");
    const Window firstWindow = initial.front();
    Require(first.value->ActivateEx(manager.value.Get(), manager.client, 0) == E_UNEXPECTED,
        "duplicate activation of one instance must fail");
    second.activate(manager);
    auto both = OwnedWindows();
    Require(both.size() == 2, "two service instances must own independent message windows");
    Window secondWindow = both[0].handle == firstWindow.handle ? both[1] : both[0];
    Require(firstWindow.className != secondWindow.className, "two instances reused a window class");
    first.deactivate();
    RequireRemoved(firstWindow, module);
    Require(OwnedWindows().size() == 1 && IsWindow(secondWindow.handle),
        "first deactivation affected the second instance");
    second.deactivate();
    RequireRemoved(secondWindow, module);
    Require(OwnedWindows().empty(), "service message window leaked after pair deactivation");
    // Repeated Deactivate is harmless and does not underflow the unload guard.
    RequireHr(first.value->Deactivate(), "repeated first Deactivate");
    RequireHr(second.value->Deactivate(), "repeated second Deactivate");
}

void RejectedActivation(GetClassObject getClass, ThreadManager& manager) {
    Service secure(getClass), comless(getClass);
    Require(secure.value->ActivateEx(manager.value.Get(), manager.client, TF_TMAE_SECUREMODE) == E_ACCESSDENIED,
        "secure mode must be rejected");
    Require(comless.value->ActivateEx(manager.value.Get(), manager.client, TF_TMAE_COMLESS) == E_ACCESSDENIED,
        "unsupported COM-less mode must be rejected");
    Require(OwnedWindows().empty(), "rejected activation created a message window");
}

void CheckFactoryReferences(GetClassObject getClass, CanUnloadNow unload) {
    Require(unload() == S_OK, "fresh DLL must be unloadable");
    ComPtr<IClassFactory> factory;
    RequireHr(getClass(stoom::ServiceId, IID_PPV_ARGS(&factory)), "get factory reference");
    Require(unload() == S_FALSE, "factory reference must block DLL unload");
    RequireHr(factory->LockServer(TRUE), "lock DLL server");
    factory.Reset();
    Require(unload() == S_FALSE, "server lock must block DLL unload");
    RequireHr(getClass(stoom::ServiceId, IID_PPV_ARGS(&factory)), "get factory to unlock");
    RequireHr(factory->LockServer(FALSE), "unlock DLL server");
    factory.Reset();
    Require(unload() == S_OK, "released factory and server lock must allow unload");
}

void ConcurrentCycles(GetClassObject getClass, HMODULE module, CanUnloadNow unload) {
    std::atomic<int> ready{0};
    std::atomic<bool> release{false};
    std::string errors[2];
    auto run = [&](int index) {
        try {
            ComScope com;
            ThreadManager manager;
            Service held(getClass);
            held.activate(manager);
            Require(OwnedWindows().size() == 1, "concurrent STA activation missing message window");
            ready.fetch_add(1);
            while (!release.load()) std::this_thread::yield();
            held.deactivate();
            for (int cycle = 0; cycle < 12; ++cycle) PairCycle(getClass, module, manager);
        } catch (const std::exception& error) {
            errors[index] = error.what();
            ready.fetch_add(1);
        }
    };
    std::thread first(run, 0), second(run, 1);
    const ULONGLONG deadline = GetTickCount64() + 10000;
    while (ready.load() != 2 && GetTickCount64() < deadline) std::this_thread::yield();
    const bool bothReady = ready.load() == 2;
    const HRESULT whileHeld = unload();
    release.store(true);
    first.join();
    second.join();
    Require(bothReady, "concurrent lifecycle setup exceeded 10 seconds");
    for (const auto& error : errors) if (!error.empty()) throw std::runtime_error(error);
    Require(whileHeld == S_FALSE, "live concurrent services must block DLL unload");
    Require(unload() == S_OK, "concurrent STAs leaked service/class references");
}

struct Module {
    HMODULE value = nullptr;
    explicit Module(const wchar_t* path) {
        value = LoadLibraryExW(path, nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
        if (!value) RequireHr(HRESULT_FROM_WIN32(GetLastError()), "load tested DLL");
    }
    ~Module() { if (value) FreeLibrary(value); }
};
}

int wmain(int argc, wchar_t** argv) {
    if (argc != 2) {
        std::puts("Usage: service_lifecycle.exe <absolute-or-relative STOOMTextService.dll path>");
        return 2;
    }
    wchar_t fullPath[32768]{};
    DWORD length = GetFullPathNameW(argv[1], ARRAYSIZE(fullPath), fullPath, nullptr);
    if (!length || length >= ARRAYSIZE(fullPath)) {
        std::puts("FAIL: invalid DLL path");
        return 1;
    }
    try {
        ComScope com;
        ThreadManager manager;
        for (int load = 0; load < 8; ++load) {
            Module module(fullPath);
            auto getClass = reinterpret_cast<GetClassObject>(GetProcAddress(module.value, "DllGetClassObject"));
            auto unload = reinterpret_cast<CanUnloadNow>(GetProcAddress(module.value, "DllCanUnloadNow"));
            Require(getClass && unload, "missing undecorated COM exports");
            CheckFactoryReferences(getClass, unload);
            RejectedActivation(getClass, manager);
            Require(unload() == S_OK, "rejected activation leaked references");
            for (int cycle = 0; cycle < 12; ++cycle) PairCycle(getClass, module.value, manager);
            Require(unload() == S_OK, "sequential cycles leaked service/class references");
            if (load == 0) ConcurrentCycles(getClass, module.value, unload);
            Require(OwnedWindows().empty(), "test thread still owns service windows before DLL unload");
            Require(unload() == S_OK, "DLL refuses unload after all lifecycle checks");
        }
        std::puts("PASS: 8 DLL load/unload rounds, 96 sequential two-instance cycles, "
                  "24 concurrent two-instance cycles, rejected modes and COM unload references.");
        std::puts("Scope: direct service lifecycle with real private TSF thread managers only; "
                  "no global registration/profile activation, focused documents, text capture or replacement.");
        return 0;
    } catch (const std::exception& error) {
        std::printf("FAIL: %s\n", error.what());
        return 1;
    }
}
