// Auxiliary TSF service. It never handles or remaps keyboard events.
#include <windows.h>
#include <msctf.h>
#include <wrl/client.h>
#include <string>
#include <vector>
#include <memory>
#include <new>
#include "protocol.h"
#include "range.h"
using Microsoft::WRL::ComPtr;
HINSTANCE g_module = nullptr;
static LONG objects = 0;
static LONG windowClasses = 0;

namespace stoom {
static bool SameUser(DWORD pid) {
    DWORD theirSession=0, ourSession=0;
    if (!ProcessIdToSessionId(pid,&theirSession) ||
        !ProcessIdToSessionId(GetCurrentProcessId(),&ourSession) || theirSession!=ourSession) return false;
    HANDLE process=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,pid), theirs=nullptr, ours=nullptr;
    if(!process) return false;
    bool equal=false;
    if(OpenProcessToken(process,TOKEN_QUERY,&theirs) && OpenProcessToken(GetCurrentProcess(),TOKEN_QUERY,&ours)) {
        DWORD a=0,b=0; GetTokenInformation(theirs,TokenUser,nullptr,0,&a); GetTokenInformation(ours,TokenUser,nullptr,0,&b);
        std::vector<BYTE> av(a),bv(b);
        if(a && b && GetTokenInformation(theirs,TokenUser,av.data(),a,&a) && GetTokenInformation(ours,TokenUser,bv.data(),b,&b))
            equal=!!EqualSid(reinterpret_cast<TOKEN_USER*>(av.data())->User.Sid,reinterpret_cast<TOKEN_USER*>(bv.data())->User.Sid);
    }
    if(theirs)CloseHandle(theirs); if(ours)CloseHandle(ours); CloseHandle(process); return equal;
}

struct Request {
    HANDLE mapping=nullptr,event=nullptr;
    Packet *shared=nullptr, input{};
    ~Request(){if(shared)UnmapViewOfFile(shared);if(mapping)CloseHandle(mapping);if(event)CloseHandle(event);}
    void Finish(HRESULT hr,const GUID& id=GUID_NULL,const std::wstring& text=L"") {
        shared->snapshot=id; shared->length=static_cast<uint32_t>(text.size());
        if(!text.empty())memcpy(shared->text,text.data(),text.size()*sizeof(wchar_t));
        shared->text[text.size()]=0; shared->status=hr;
        InterlockedExchange(reinterpret_cast<volatile LONG*>(&shared->complete),1); SetEvent(event);
    }
};

class Service;
class Edit final: public ITfEditSession {
    LONG refs_=1; Service *owner_; ComPtr<ITfContext> context_; std::shared_ptr<Request> request_;
public:
    Edit(Service*,ITfContext*,std::shared_ptr<Request>);
    ~Edit();
    STDMETHODIMP QueryInterface(REFIID id,void**out) override {
        if(!out)return E_POINTER;*out=nullptr;
        if(id==IID_IUnknown||id==IID_ITfEditSession){*out=static_cast<ITfEditSession*>(this);AddRef();return S_OK;}return E_NOINTERFACE;
    }
    STDMETHODIMP_(ULONG) AddRef() override{return InterlockedIncrement(&refs_);}
    STDMETHODIMP_(ULONG) Release() override{ULONG n=InterlockedDecrement(&refs_);if(!n)delete this;return n;}
    STDMETHODIMP DoEditSession(TfEditCookie cookie) override;
};

class Service final: public ITfTextInputProcessorEx, public ITfThreadMgrEventSink, public ITfTextEditSink {
    LONG refs_=1; ComPtr<ITfThreadMgr> manager_; TfClientId client_=TF_CLIENTID_NULL;
    DWORD threadSink_=TF_INVALID_COOKIE, editSink_=TF_INVALID_COOKIE;
    ComPtr<ITfContext> watched_; HWND window_=nullptr;
    std::wstring windowClass_;
    RangeSnapshot snapshot_{}; GUID id_=GUID_NULL; bool valid_=false, applying_=false, active_=false;
    uint64_t capturedAt_=0;
    uintptr_t generation_=0;
    void Invalidate(){
        valid_=false;++generation_;
        // Release abandoned document references after TSF notification returns.
        if(window_)PostMessageW(window_,WM_APP+1,generation_,0);
    }
    void Unwatch(){
        if(watched_ && editSink_!=TF_INVALID_COOKIE){ComPtr<ITfSource>s;if(SUCCEEDED(watched_.As(&s)))s->UnadviseSink(editSink_);}
        editSink_=TF_INVALID_COOKIE;watched_.Reset();
    }
    HRESULT Watch(ITfContext*context){
        Unwatch(); ComPtr<ITfSource>s; HRESULT hr=context->QueryInterface(IID_PPV_ARGS(&s));
        if(SUCCEEDED(hr))hr=s->AdviseSink(IID_ITfTextEditSink,static_cast<ITfTextEditSink*>(this),&editSink_);
        if(SUCCEEDED(hr))watched_=context;return hr;
    }
    bool FocusMatches(const Packet&p,ITfContext *expected=nullptr){
        if(!active_||!manager_||p.thread!=GetCurrentThreadId()||GetTickCount64()>p.deadline)return false;
        HWND foreground=GetForegroundWindow();GUITHREADINFO gi{sizeof(gi)};
        if(reinterpret_cast<uintptr_t>(foreground)!=p.foreground||GetWindowThreadProcessId(reinterpret_cast<HWND>(static_cast<uintptr_t>(p.keyboard)),nullptr)!=p.thread||
            !GetGUIThreadInfo(p.thread,&gi)||reinterpret_cast<uintptr_t>(gi.hwndFocus)!=p.keyboard)return false;
        if(expected){ComPtr<ITfDocumentMgr>d;ComPtr<ITfContext>c;
            if(FAILED(manager_->GetFocus(&d))||!d||FAILED(d->GetTop(&c))||!c)return false;
            ComPtr<IUnknown>a,b;c.As(&a);expected->QueryInterface(IID_PPV_ARGS(&b));if(a.Get()!=b.Get())return false;
        }
        return true;
    }
    LRESULT Receive(HWND sender,const COPYDATASTRUCT*cd){
        if(!cd||cd->dwData!=Magic||cd->cbData!=sizeof(Notice)||!cd->lpData)return 0;
        Notice notice{};memcpy(&notice,cd->lpData,sizeof(notice));
        if(notice.magic!=Magic||notice.name[95]!=0||wcsncmp(notice.name,MappingPrefix,wcslen(MappingPrefix)))return 0;
        DWORD senderPid=0;GetWindowThreadProcessId(sender,&senderPid);
        if(!senderPid||!SameUser(senderPid))return 0;
        // The sender PID is part of the unpredictable per-request object name.
        wchar_t prefix[64];swprintf_s(prefix,L"Local\\STOOM.TSF.%lu.",senderPid);
        if(wcsncmp(notice.name,prefix,wcslen(prefix)))return 0;
        auto req=std::make_shared<Request>();
        req->mapping=OpenFileMappingW(FILE_MAP_READ|FILE_MAP_WRITE,FALSE,notice.name);
        if(!req->mapping)return 0;
        req->shared=static_cast<Packet*>(MapViewOfFile(req->mapping,FILE_MAP_READ|FILE_MAP_WRITE,0,0,sizeof(Packet)));
        std::wstring eventName=std::wstring(notice.name)+L".done";
        req->event=OpenEventW(EVENT_MODIFY_STATE,FALSE,eventName.c_str());
        if(!req->shared||!req->event)return 0;
        memcpy(&req->input,req->shared,sizeof(Packet));const auto&p=req->input;
        if(p.magic!=Magic||p.version!=ProtocolVersion||p.client!=senderPid||p.complete||
           p.length>16000||p.text[p.length]!=0||p.deadline>GetTickCount64()+3000)return 0;
        if(!FocusMatches(p)){req->Finish(HRESULT_FROM_WIN32(ERROR_CANCELLED));return 1;}
        if(p.operation==CancelOp){if(p.snapshot==id_)Invalidate();req->Finish(S_OK);return 1;}
        if(p.operation!=CaptureOp&&p.operation!=ApplyOp)return 0;
        ComPtr<ITfDocumentMgr>doc;ComPtr<ITfContext>context;
        if(FAILED(manager_->GetFocus(&doc))||!doc||FAILED(doc->GetTop(&context))||!context){req->Finish(E_NOINTERFACE);return 1;}
        auto edit=new(std::nothrow)Edit(this,context.Get(),req);
        if(!edit){req->Finish(E_OUTOFMEMORY);return 1;}
        HRESULT session=E_FAIL;
        HRESULT hr=context->RequestEditSession(client_,edit,TF_ES_ASYNCDONTCARE|(p.operation==ApplyOp?TF_ES_READWRITE:TF_ES_READ),&session);
        edit->Release();
        if(FAILED(hr))req->Finish(hr);
        else if(FAILED(session))req->Finish(session);
        return 1;
    }
    static LRESULT CALLBACK WndProc(HWND w,UINT msg,WPARAM wp,LPARAM lp){
        auto self=reinterpret_cast<Service*>(GetWindowLongPtrW(w,GWLP_USERDATA));
        if(msg==WM_NCCREATE){self=static_cast<Service*>(reinterpret_cast<CREATESTRUCTW*>(lp)->lpCreateParams);SetWindowLongPtrW(w,GWLP_USERDATA,reinterpret_cast<LONG_PTR>(self));}
        if(msg==WM_COPYDATA&&self){try{return self->Receive(reinterpret_cast<HWND>(wp),reinterpret_cast<COPYDATASTRUCT*>(lp));}catch(...){return 0;}}
        if(msg==WM_APP+1&&self){
            if(!self->valid_&&wp==self->generation_){self->Unwatch();self->snapshot_=RangeSnapshot{};KillTimer(w,1);}
            return 0;
        }
        if(msg==WM_TIMER&&wp==1&&self){if(self->valid_&&GetTickCount64()-self->capturedAt_>=120000)self->Invalidate();return 0;}
        return DefWindowProcW(w,msg,wp,lp);
    }
public:
    Service(){InterlockedIncrement(&objects);}
    ~Service(){InterlockedDecrement(&objects);}
    STDMETHODIMP QueryInterface(REFIID iid,void**out)override{
        if(!out)return E_POINTER;*out=nullptr;
        if(iid==IID_IUnknown||iid==IID_ITfTextInputProcessor||iid==IID_ITfTextInputProcessorEx)*out=static_cast<ITfTextInputProcessorEx*>(this);
        else if(iid==IID_ITfThreadMgrEventSink)*out=static_cast<ITfThreadMgrEventSink*>(this);
        else if(iid==IID_ITfTextEditSink)*out=static_cast<ITfTextEditSink*>(this);
        else return E_NOINTERFACE;AddRef();return S_OK;
    }
    STDMETHODIMP_(ULONG) AddRef()override{return InterlockedIncrement(&refs_);}
    STDMETHODIMP_(ULONG) Release()override{ULONG n=InterlockedDecrement(&refs_);if(!n)delete this;return n;}
    STDMETHODIMP Activate(ITfThreadMgr*m,TfClientId id)override{return ActivateEx(m,id,0);}
    STDMETHODIMP ActivateEx(ITfThreadMgr*m,TfClientId id,DWORD flags)override{
        if(active_)return E_UNEXPECTED;
        if(flags&(TF_TMAE_SECUREMODE|TF_TMAE_COMLESS))return E_ACCESSDENIED;
        manager_=m;client_=id;ComPtr<ITfSource>source;HRESULT hr=manager_.As(&source);
        if(SUCCEEDED(hr))hr=source->AdviseSink(IID_ITfThreadMgrEventSink,static_cast<ITfThreadMgrEventSink*>(this),&threadSink_);
        if(FAILED(hr)){manager_.Reset();return hr;}
        // Per-instance class ownership: another TSF STA can activate/deactivate
        // concurrently without leaving a class pointing into an unloaded DLL.
        wchar_t cls[128];swprintf_s(cls,L"%s.%lu.%p",WindowClass,GetCurrentThreadId(),this);windowClass_=cls;
        WNDCLASSW wc{};wc.lpfnWndProc=WndProc;wc.hInstance=g_module;wc.lpszClassName=windowClass_.c_str();
        if(!RegisterClassW(&wc)){DWORD error=GetLastError();windowClass_.clear();Deactivate();return HRESULT_FROM_WIN32(error);}
        InterlockedIncrement(&windowClasses);
        wchar_t name[80];swprintf_s(name,L"STOOM.TSF.%lu.%lu",GetCurrentProcessId(),GetCurrentThreadId());
        window_=CreateWindowExW(0,windowClass_.c_str(),name,0,0,0,0,0,HWND_MESSAGE,nullptr,g_module,this);
        if(!window_){Deactivate();return E_FAIL;}active_=true;return S_OK;
    }
    STDMETHODIMP Deactivate()override{
        active_=false;Invalidate();Unwatch();snapshot_=RangeSnapshot{};
        if(window_){DestroyWindow(window_);window_=nullptr;}
        if(!windowClass_.empty()){
            if(UnregisterClassW(windowClass_.c_str(),g_module))InterlockedDecrement(&windowClasses);
            windowClass_.clear();
        }
        if(manager_&&threadSink_!=TF_INVALID_COOKIE){ComPtr<ITfSource>s;if(SUCCEEDED(manager_.As(&s)))s->UnadviseSink(threadSink_);}
        threadSink_=TF_INVALID_COOKIE;manager_.Reset();client_=TF_CLIENTID_NULL;return S_OK;
    }
    STDMETHODIMP OnInitDocumentMgr(ITfDocumentMgr*)override{return S_OK;}
    STDMETHODIMP OnUninitDocumentMgr(ITfDocumentMgr*)override{Invalidate();return S_OK;}
    STDMETHODIMP OnSetFocus(ITfDocumentMgr*,ITfDocumentMgr*)override{Invalidate();return S_OK;}
    STDMETHODIMP OnPushContext(ITfContext*)override{Invalidate();return S_OK;}
    STDMETHODIMP OnPopContext(ITfContext*)override{Invalidate();return S_OK;}
    STDMETHODIMP OnEndEdit(ITfContext*,TfEditCookie,ITfEditRecord*record)override{
        if(!valid_||applying_)return S_OK;
        BOOL selection=FALSE;ComPtr<IEnumTfRanges>ranges;ComPtr<ITfRange>range;ULONG n=0;
        if(FAILED(record->GetSelectionStatus(&selection))||selection){Invalidate();return S_OK;}
        if(FAILED(record->GetTextAndPropertyUpdates(TF_GTP_INCL_TEXT,nullptr,0,&ranges))||
           (ranges&&ranges->Next(1,&range,&n)==S_OK&&n))Invalidate();
        return S_OK;
    }
    HRESULT Perform(ITfContext*context,TfEditCookie cookie,Request&r){
        const auto&p=r.input;
        if(!FocusMatches(p,context)){r.Finish(HRESULT_FROM_WIN32(ERROR_CANCELLED));return S_OK;}
        if(p.operation==CaptureOp){
            Invalidate();Unwatch();snapshot_=RangeSnapshot{};
            HRESULT hr=Capture(context,cookie,snapshot_);
            if(hr==S_OK)hr=Watch(context);
            if(hr==S_OK)hr=CoCreateGuid(&id_);
            if(hr==S_OK){valid_=true;capturedAt_=GetTickCount64();SetTimer(window_,1,120000,nullptr);r.Finish(S_OK,id_,snapshot_.original);}
            else r.Finish(hr);
        }else{
            if(!valid_||p.snapshot!=id_||GetTickCount64()-capturedAt_>120000){r.Finish(HRESULT_FROM_WIN32(ERROR_REVISION_MISMATCH));return S_OK;}
            // SetText is issued at most once; no paste or fallback after this point.
            valid_=false;applying_=true;
            HRESULT hr=Apply(context,cookie,snapshot_,std::wstring(p.text,p.length),[&]{return FocusMatches(p,context);});
            applying_=false;r.Finish(hr,id_);snapshot_=RangeSnapshot{};Unwatch();
        }
        return S_OK;
    }
};
Edit::Edit(Service*s,ITfContext*c,std::shared_ptr<Request>r):owner_(s),context_(c),request_(std::move(r)){owner_->AddRef();}
Edit::~Edit(){owner_->Release();}
HRESULT Edit::DoEditSession(TfEditCookie cookie){try{return owner_->Perform(context_.Get(),cookie,*request_);}catch(...){request_->Finish(E_FAIL);return E_FAIL;}}

class Factory final:public IClassFactory{
    LONG refs_=1;
public:
    Factory(){InterlockedIncrement(&objects);}~Factory(){InterlockedDecrement(&objects);}
    STDMETHODIMP QueryInterface(REFIID id,void**out)override{if(!out)return E_POINTER;*out=nullptr;if(id!=IID_IUnknown&&id!=IID_IClassFactory)return E_NOINTERFACE;*out=this;AddRef();return S_OK;}
    STDMETHODIMP_(ULONG) AddRef()override{return InterlockedIncrement(&refs_);}
    STDMETHODIMP_(ULONG) Release()override{ULONG n=InterlockedDecrement(&refs_);if(!n)delete this;return n;}
    STDMETHODIMP CreateInstance(IUnknown*outer,REFIID id,void**out)override{if(!out)return E_POINTER;*out=nullptr;if(outer)return CLASS_E_NOAGGREGATION;auto s=new(std::nothrow)Service;if(!s)return E_OUTOFMEMORY;HRESULT hr=s->QueryInterface(id,out);s->Release();return hr;}
    STDMETHODIMP LockServer(BOOL lock)override{if(lock)InterlockedIncrement(&objects);else InterlockedDecrement(&objects);return S_OK;}
};
}
extern "C" HRESULT __stdcall DllGetClassObject(REFCLSID cls,REFIID iid,void**out){
    if(!out)return E_POINTER;*out=nullptr;if(cls!=stoom::ServiceId)return CLASS_E_CLASSNOTAVAILABLE;
    auto f=new(std::nothrow)stoom::Factory;if(!f)return E_OUTOFMEMORY;HRESULT hr=f->QueryInterface(iid,out);f->Release();return hr;
}
extern "C" HRESULT __stdcall DllCanUnloadNow(){return objects==0&&windowClasses==0?S_OK:S_FALSE;}
BOOL WINAPI DllMain(HINSTANCE module,DWORD reason,LPVOID){if(reason==DLL_PROCESS_ATTACH){g_module=module;DisableThreadLibraryCalls(module);}return TRUE;}
