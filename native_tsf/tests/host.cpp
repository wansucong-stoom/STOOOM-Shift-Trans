// An owned in-memory Windows TSF application. The ranges, edit cookies and
// locks below are supplied by msctf.dll, not mocked ITfRange implementations.
// Never registers a service, sets global focus, or reads another application's
// document. TF_TMAE_NOACTIVATETIP keeps installed TIPs out of this fixture.
#include "../range.h"
#include "../protocol.h"
#include <textstor.h>
#include <initguid.h>
#include <inputscope.h>
#include <olectl.h>
#include <algorithm>
#include <functional>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <cstdio>
#include <vector>

using Microsoft::WRL::ComPtr;

static void Require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
static void Check(HRESULT hr, const char* message) {
    if (FAILED(hr)) {
        std::ostringstream error;
        error << message << " HRESULT=0x" << std::hex << static_cast<unsigned long>(hr);
        throw std::runtime_error(error.str());
    }
}

class Store final : public ITextStoreACP, public ITfInputScope,
                    public ITfContextOwnerCompositionSink {
    ULONG refs_ = 1;
    DWORD lock_ = 0, sinkMask_ = 0;
    std::vector<DWORD> queued_;
    bool scopeRequested_ = false;
    ComPtr<ITextStoreACPSink> sink_;
    HRESULT NeedRead() const { return lock_ & TS_LF_READ ? S_OK : TS_E_NOLOCK; }
    HRESULT NeedWrite() const { return (lock_ & TS_LF_READWRITE) == TS_LF_READWRITE ? S_OK : TS_E_NOLOCK; }
    bool Bounds(LONG a, LONG b) const { return a >= 0 && b >= a && b <= static_cast<LONG>(text.size()); }
    HRESULT Attrs(ULONG count, const TS_ATTRID* ids) {
        scopeRequested_ = false;
        for (ULONG i=0; i<count; ++i) if (ids[i] == GUID_PROP_INPUTSCOPE) scopeRequested_ = true;
        return S_OK;
    }
public:
    std::wstring text;
    TS_SELECTION_ACP selected{};
    bool readonly = false;
    bool rejectCaret = false;
    InputScope scope = IS_DEFAULT;
    unsigned reads = 0, writes = 0, locks = 0, scopesRead = 0;
    explicit Store(std::wstring value, LONG start, LONG end) : text(std::move(value)) {
        selected = {start,end,{start == end ? TS_AE_NONE : TS_AE_END,FALSE}};
    }
    STDMETHODIMP QueryInterface(REFIID id, void** out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        if (id == IID_IUnknown || id == IID_ITextStoreACP) *out = static_cast<ITextStoreACP*>(this);
        else if (id == IID_ITfInputScope) *out = static_cast<ITfInputScope*>(this);
        else if (id == IID_ITfContextOwnerCompositionSink) *out = static_cast<ITfContextOwnerCompositionSink*>(this);
        else return E_NOINTERFACE;
        AddRef(); return S_OK;
    }
    STDMETHODIMP_(ULONG) AddRef() override { return ++refs_; }
    STDMETHODIMP_(ULONG) Release() override { auto n = --refs_; if (!n) delete this; return n; }
    STDMETHODIMP AdviseSink(REFIID id, IUnknown* unknown, DWORD mask) override {
        if (id != IID_ITextStoreACPSink || !unknown) return E_INVALIDARG;
        ComPtr<ITextStoreACPSink> candidate;
        HRESULT hr = unknown->QueryInterface(IID_PPV_ARGS(&candidate));
        if (FAILED(hr)) return hr;
        if (sink_ && candidate.Get() != sink_.Get()) return CONNECT_E_ADVISELIMIT;
        sink_ = candidate; sinkMask_ = mask; return S_OK;
    }
    STDMETHODIMP UnadviseSink(IUnknown* unknown) override {
        ComPtr<IUnknown> oldId, newId;
        if (!sink_ || !unknown) return CONNECT_E_NOCONNECTION;
        sink_.As(&oldId); unknown->QueryInterface(IID_PPV_ARGS(&newId));
        if (oldId.Get() != newId.Get()) return CONNECT_E_NOCONNECTION;
        sink_.Reset(); return S_OK;
    }
    STDMETHODIMP RequestLock(DWORD flags, HRESULT* session) override {
        if (!session || !sink_) return E_INVALIDARG;
        if (lock_) {
            if (flags & TS_LF_SYNC) { *session = TS_E_SYNCHRONOUS; return S_OK; }
            queued_.push_back(flags); *session = TS_S_ASYNC; return S_OK;
        }
        lock_ = flags; ++locks;
        *session = sink_->OnLockGranted(flags);
        lock_ = 0;
        for (unsigned i=0; !queued_.empty() && i<32; ++i) {
            const DWORD pending = queued_.front(); queued_.erase(queued_.begin());
            lock_ = pending; ++locks; sink_->OnLockGranted(pending); lock_ = 0;
        }
        return S_OK;
    }
    STDMETHODIMP GetStatus(TS_STATUS* status) override {
        if (!status) return E_POINTER;
        status->dwDynamicFlags = readonly ? TS_SD_READONLY : 0;
        status->dwStaticFlags = TS_SS_NOHIDDENTEXT; return S_OK;
    }
    STDMETHODIMP QueryInsert(LONG a, LONG b, ULONG, LONG* start, LONG* end) override {
        if (!start || !end || !Bounds(a,b)) return E_INVALIDARG;
        *start = a; *end = b; return S_OK;
    }
    STDMETHODIMP GetSelection(ULONG index, ULONG count, TS_SELECTION_ACP* values, ULONG* fetched) override {
        if (FAILED(NeedRead())) return TS_E_NOLOCK;
        if (!values || !fetched) return E_POINTER;
        *fetched = 0;
        if (index != 0 && index != TS_DEFAULT_SELECTION) return TS_E_NOSELECTION;
        if (count) { values[0] = selected; *fetched = 1; }
        return S_OK;
    }
    STDMETHODIMP SetSelection(ULONG count, const TS_SELECTION_ACP* values) override {
        if (FAILED(NeedWrite())) return TS_E_NOLOCK;
        if (count != 1 || !values || !Bounds(values[0].acpStart,values[0].acpEnd)) return E_INVALIDARG;
        if (rejectCaret) return E_FAIL;
        selected = values[0]; return S_OK;
    }
    STDMETHODIMP GetText(LONG a, LONG b, WCHAR* plain, ULONG capacity, ULONG* copied,
        TS_RUNINFO* runs, ULONG runCapacity, ULONG* runsCopied, LONG* next) override {
        if (FAILED(NeedRead())) return TS_E_NOLOCK;
        if (b == -1) b = static_cast<LONG>(text.size());
        if (!Bounds(a,b) || !copied || !runsCopied || !next || (capacity && !plain) || (runCapacity && !runs)) return E_INVALIDARG;
        ++reads; *copied = 0; *runsCopied = 0;
        ULONG length = static_cast<ULONG>(b-a);
        if (capacity) {
            length = (std::min)(length,capacity);
            std::copy_n(text.data()+a,length,plain); *copied = length;
        }
        if (runCapacity && length) { runs[0] = {length,TS_RT_PLAIN}; *runsCopied = 1; }
        *next = a + length; return S_OK;
    }
    STDMETHODIMP SetText(DWORD, LONG a, LONG b, const WCHAR* value, ULONG count, TS_TEXTCHANGE* change) override {
        if (FAILED(NeedWrite())) return TS_E_NOLOCK;
        if (readonly) return TS_E_READONLY;
        if (!Bounds(a,b) || !change || (count && !value)) return E_INVALIDARG;
        ++writes;
        text.replace(a,b-a,value,count);
        *change = {a,b,a+static_cast<LONG>(count)};
        selected = {change->acpNewEnd,change->acpNewEnd,{TS_AE_NONE,FALSE}};
        return S_OK;
    }
    STDMETHODIMP GetFormattedText(LONG,LONG,IDataObject** out) override { if (out) *out=nullptr; return E_NOTIMPL; }
    STDMETHODIMP GetEmbedded(LONG,REFGUID,REFIID,IUnknown** out) override { if(out)*out=nullptr; return E_NOTIMPL; }
    STDMETHODIMP QueryInsertEmbedded(const GUID*,const FORMATETC*,BOOL* yes) override { if(!yes)return E_POINTER;*yes=FALSE;return S_OK; }
    STDMETHODIMP InsertEmbedded(DWORD,LONG,LONG,IDataObject*,TS_TEXTCHANGE*) override { return E_NOTIMPL; }
    STDMETHODIMP InsertTextAtSelection(DWORD flags,const WCHAR* value,ULONG count,LONG* a,LONG* b,TS_TEXTCHANGE* change) override {
        if(FAILED(NeedWrite()))return TS_E_NOLOCK;
        if(a)*a=selected.acpStart;if(b)*b=selected.acpEnd;
        if(flags&TS_IAS_QUERYONLY)return S_OK;
        return SetText(0,selected.acpStart,selected.acpEnd,value,count,change);
    }
    STDMETHODIMP InsertEmbeddedAtSelection(DWORD,IDataObject*,LONG*,LONG*,TS_TEXTCHANGE*) override { return E_NOTIMPL; }
    STDMETHODIMP RequestSupportedAttrs(DWORD,ULONG count,const TS_ATTRID* ids) override { return Attrs(count,ids); }
    STDMETHODIMP RequestAttrsAtPosition(LONG,ULONG count,const TS_ATTRID* ids,DWORD) override { return Attrs(count,ids); }
    STDMETHODIMP RequestAttrsTransitioningAtPosition(LONG,ULONG,const TS_ATTRID*,DWORD) override { scopeRequested_=false;return S_OK; }
    STDMETHODIMP FindNextAttrTransition(LONG,LONG halt,ULONG,const TS_ATTRID*,DWORD,LONG* next,BOOL* found,LONG* offset) override {
        if(!next||!found||!offset)return E_POINTER;
        *next=halt;*found=FALSE;*offset=0;return S_OK;
    }
    STDMETHODIMP RetrieveRequestedAttrs(ULONG count,TS_ATTRVAL* values,ULONG* fetched) override {
        if(!fetched || (count&&!values))return E_POINTER;*fetched=0;
        if(count&&scopeRequested_){
            values[0].idAttr=GUID_PROP_INPUTSCOPE;values[0].dwOverlapId=0;
            VariantInit(&values[0].varValue);values[0].varValue.vt=VT_UNKNOWN;
            values[0].varValue.punkVal=static_cast<ITfInputScope*>(this);AddRef();
            scopeRequested_=false;*fetched=1;
        }
        return S_OK;
    }
    STDMETHODIMP GetEndACP(LONG* end) override { if(FAILED(NeedRead()))return TS_E_NOLOCK;if(!end)return E_POINTER;*end=static_cast<LONG>(text.size());return S_OK; }
    STDMETHODIMP GetActiveView(TsViewCookie* view) override { if(!view)return E_POINTER;*view=1;return S_OK; }
    STDMETHODIMP GetACPFromPoint(TsViewCookie,const POINT*,DWORD,LONG*) override { return TS_E_NOLAYOUT; }
    STDMETHODIMP GetTextExt(TsViewCookie,LONG,LONG,RECT* rect,BOOL* clipped) override { if(!rect||!clipped)return E_POINTER;*rect={0,0,100,20};*clipped=FALSE;return S_OK; }
    STDMETHODIMP GetScreenExt(TsViewCookie,RECT* rect) override { if(!rect)return E_POINTER;*rect={0,0,100,20};return S_OK; }
    STDMETHODIMP GetWnd(TsViewCookie,HWND* window) override { if(!window)return E_POINTER;*window=nullptr;return S_OK; }
    STDMETHODIMP GetInputScopes(InputScope** values,UINT* count) override {
        if(!values||!count)return E_POINTER;
        *values=static_cast<InputScope*>(CoTaskMemAlloc(sizeof(InputScope)));if(!*values)return E_OUTOFMEMORY;
        ++scopesRead;**values=scope;*count=1;return S_OK;
    }
    STDMETHODIMP GetPhrase(BSTR** values,UINT* count) override { if(values)*values=nullptr;if(count)*count=0;return S_FALSE; }
    STDMETHODIMP GetRegularExpression(BSTR* value) override { if(value)*value=nullptr;return S_FALSE; }
    STDMETHODIMP GetSRGS(BSTR* value) override { if(value)*value=nullptr;return S_FALSE; }
    STDMETHODIMP GetXML(BSTR* value) override { if(value)*value=nullptr;return S_FALSE; }
    STDMETHODIMP OnStartComposition(ITfCompositionView*,BOOL* accept) override { if(!accept)return E_POINTER;*accept=TRUE;return S_OK; }
    STDMETHODIMP OnUpdateComposition(ITfCompositionView*,ITfRange*) override { return S_OK; }
    STDMETHODIMP OnEndComposition(ITfCompositionView*) override { return S_OK; }
    void ExternalReplace(LONG a,LONG b,const std::wstring& value) {
        Require(!lock_,"external edit while locked");
        text.replace(a,b-a,value);
        TS_TEXTCHANGE change{a,b,a+static_cast<LONG>(value.size())};
        if(sink_ && (sinkMask_&TS_AS_TEXT_CHANGE))Check(sink_->OnTextChange(0,&change),"OnTextChange");
    }
};

class Edit final : public ITfEditSession {
    ULONG refs_=1;
    std::function<HRESULT(TfEditCookie)> work_;
public:
    HRESULT result=E_PENDING; bool completed=false;
    explicit Edit(std::function<HRESULT(TfEditCookie)> fn):work_(std::move(fn)){}
    STDMETHODIMP QueryInterface(REFIID id,void** out) override { if(!out)return E_POINTER;*out=nullptr;if(id!=IID_IUnknown&&id!=IID_ITfEditSession)return E_NOINTERFACE;*out=this;AddRef();return S_OK; }
    STDMETHODIMP_(ULONG) AddRef() override {return ++refs_;}
    STDMETHODIMP_(ULONG) Release() override {auto n=--refs_;if(!n)delete this;return n;}
    STDMETHODIMP DoEditSession(TfEditCookie cookie) override { result=work_(cookie);completed=true;return result; }
};

class Fixture {
public:
    ComPtr<ITfThreadMgr> manager;
    ComPtr<ITfDocumentMgr> document;
    ComPtr<ITfContext> context;
    ComPtr<Store> store;
    TfClientId client=TF_CLIENTID_NULL;
    Fixture(std::wstring text,LONG a,LONG b) {
        Check(CoCreateInstance(CLSID_TF_ThreadMgr,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&manager)),"Create ThreadMgr");
        ComPtr<ITfThreadMgrEx> ex;Check(manager.As(&ex),"ThreadMgrEx");
        Check(ex->ActivateEx(&client,TF_TMAE_NOACTIVATETIP|TF_TMAE_NOACTIVATEKEYBOARDLAYOUT),"ActivateEx");
        Check(manager->CreateDocumentMgr(&document),"CreateDocumentMgr");
        store.Attach(new Store(std::move(text),a,b));
        TfEditCookie ownerCookie=TF_INVALID_COOKIE;
        Check(document->CreateContext(client,0,static_cast<ITextStoreACP*>(store.Get()),&context,&ownerCookie),"CreateContext");
        Check(document->Push(context.Get()),"Push");
        Check(manager->SetFocus(document.Get()),"SetFocus owned context");
    }
    ~Fixture(){
        if(manager)manager->SetFocus(nullptr);
        if(document)document->Pop(TF_POPF_ALL);
        context.Reset();document.Reset();
        if(manager)manager->Deactivate();
    }
    HRESULT Run(bool write,std::function<HRESULT(TfEditCookie)> fn) {
        ComPtr<Edit> edit;edit.Attach(new Edit(std::move(fn)));
        HRESULT session=E_PENDING;
        Check(context->RequestEditSession(client,edit.Get(),TF_ES_ASYNCDONTCARE|(write?TF_ES_READWRITE:TF_ES_READ),&session),"RequestEditSession");
        const auto end=GetTickCount64()+2000;
        while(!edit->completed&&GetTickCount64()<end){
            MSG msg;while(PeekMessageW(&msg,nullptr,0,0,PM_REMOVE)){TranslateMessage(&msg);DispatchMessageW(&msg);}
            Sleep(1);
        }
        if(!edit->completed)Check(session,"Edit session refused");
        Require(edit->completed,"edit session timeout");return edit->result;
    }
    HRESULT Capture(stoom::RangeSnapshot& s){return Run(false,[&](TfEditCookie c){return stoom::Capture(context.Get(),c,s);});}
    HRESULT Apply(const stoom::RangeSnapshot& s,const std::wstring& replacement){return Run(true,[&](TfEditCookie c){return stoom::Apply(context.Get(),c,s,replacement);});}
};

class CompositionSink final:public ITfCompositionSink{
    ULONG refs_=1;
public:
    STDMETHODIMP QueryInterface(REFIID id,void**out)override{if(!out)return E_POINTER;*out=nullptr;if(id!=IID_IUnknown&&id!=IID_ITfCompositionSink)return E_NOINTERFACE;*out=this;AddRef();return S_OK;}
    STDMETHODIMP_(ULONG) AddRef()override{return ++refs_;}
    STDMETHODIMP_(ULONG) Release()override{auto n=--refs_;if(!n)delete this;return n;}
    STDMETHODIMP OnCompositionTerminated(TfEditCookie,ITfComposition*)override{return S_OK;}
};

static void SelectionTest(){
    Fixture f(L"앞 안녕하세요 뒤",2,7);stoom::RangeSnapshot s;
    Require(f.Capture(s)==S_OK,"capture selection");Require(s.original==L"안녕하세요","selection text");
    Require(f.Apply(s,L"Hello")==S_OK,"apply selection");
    Require(f.store->text==L"앞 Hello 뒤","selection replacement");
    Require(f.store->selected.acpStart==7&&f.store->selected.acpEnd==7,"caret at replacement end");
    Require(f.store->writes==1,"single write");Require(f.store->locks>0,"real TSF locks");
}
static void ParagraphTest(){
    Fixture f(L"첫 문단\r\n안녕하세요\r\n끝",8,8);stoom::RangeSnapshot s;
    Require(f.Capture(s)==S_OK,"capture paragraph");Require(s.original==L"안녕하세요","paragraph text");
    Require(f.Apply(s,L"Hello world")==S_OK,"apply paragraph");
    Require(f.store->text==L"첫 문단\r\nHello world\r\n끝","paragraph boundaries preserved");
    Require(f.store->selected.acpStart==17&&f.store->selected.acpEnd==17,"paragraph caret end");
}
static void ReadOnlyTest(){
    Fixture f(L"do not change",0,0);f.store->readonly=true;stoom::RangeSnapshot s;
    Require(FAILED(f.Capture(s)),"readonly must reject capture");Require(f.store->writes==0,"readonly write");
}
static void PasswordTest(InputScope scope){
    Fixture f(L"synthetic password fixture",0,0);f.store->scope=scope;stoom::RangeSnapshot s;
    const HRESULT hr=f.Capture(s);
    Require(f.store->scopesRead>0,"real TSF InputScope was not retrieved");
    Require(hr==E_ACCESSDENIED,"password must reject capture");Require(f.store->writes==0,"password write");
}
static void SourceChangedTest(){
    Fixture f(L"hello world",0,5);stoom::RangeSnapshot s;Require(f.Capture(s)==S_OK,"capture stale");
    f.store->ExternalReplace(0,5,L"other");
    Require(FAILED(f.Apply(s,L"번역")),"changed source must not apply");Require(f.store->text==L"other world"&&f.store->writes==0,"stale source changed");
}
static void SelectionChangedTest(){
    Fixture f(L"hello world",0,5);stoom::RangeSnapshot s;Require(f.Capture(s)==S_OK,"capture before selection move");
    Check(f.Run(true,[&](TfEditCookie cookie){ComPtr<ITfRange>r;HRESULT hr=f.context->GetEnd(cookie,&r);if(FAILED(hr))return hr;TF_SELECTION selection{r.Get(),{TF_AE_NONE,FALSE}};return f.context->SetSelection(cookie,1,&selection);}),"move selection");
    Require(FAILED(f.Apply(s,L"번역")),"changed selection must not apply");Require(f.store->writes==0,"selection changed write");
}
static void CompositionTest(){
    Fixture f(L"hello world",0,5);ComPtr<ITfComposition>composition;ComPtr<CompositionSink>sink;sink.Attach(new CompositionSink);
    Check(f.Run(true,[&](TfEditCookie cookie){ComPtr<ITfContextComposition>cc;HRESULT hr=f.context.As(&cc);if(FAILED(hr))return hr;TF_SELECTION selection{};ULONG count=0;hr=f.context->GetSelection(cookie,TF_DEFAULT_SELECTION,1,&selection,&count);if(FAILED(hr)||count!=1)return E_FAIL;hr=cc->StartComposition(cookie,selection.range,sink.Get(),&composition);selection.range->Release();return hr;}),"StartComposition");
    Require(!!composition,"composition must be real");stoom::RangeSnapshot s;Require(f.Capture(s)==TF_E_LOCKED,"active composition must defer capture");
    Check(f.Run(true,[&](TfEditCookie cookie){return composition->EndComposition(cookie);}),"EndComposition");
    Require(f.Capture(s)==S_OK,"capture after composition completes");
}
static void CaretFailureTest(){
    Fixture f(L"hello",0,5);stoom::RangeSnapshot s;Require(f.Capture(s)==S_OK,"capture caret failure");f.store->rejectCaret=true;
    Require(f.Apply(s,L"hi")==stoom::kAppliedCaretUnavailable,"caret failure must report applied status");
    Require(f.store->text==L"hi"&&f.store->writes==1,"caret failure must not duplicate write");
}
static void ProtectionChangedTest(){
    Fixture f(L"hello",0,5);stoom::RangeSnapshot s;Require(f.Capture(s)==S_OK,"capture before protection change");
    f.store->scope=IS_PASSWORD;
    Require(f.Apply(s,L"hi")==E_ACCESSDENIED,"scope changed to password must not apply");
    Require(f.store->text==L"hello"&&f.store->writes==0,"protection change wrote text");
}
static void LongParagraphTest(){
    Fixture f(std::wstring(stoom::kMaxSource+1,L'x'),4000,4000);stoom::RangeSnapshot s;
    Require(f.Capture(s)!=S_OK,"oversized paragraph must not truncate and apply");
    Require(f.store->writes==0,"oversized paragraph write");
}
static void ForeignContextTest(){
    Fixture first(L"same text",0,4);stoom::RangeSnapshot s;Require(first.Capture(s)==S_OK,"capture foreign context");
    Fixture second(L"same text",0,4);
    Require(FAILED(second.Apply(s,L"hi")),"identical text in a different context must not apply");
    Require(first.store->writes==0&&second.store->writes==0,"wrong-context write");
}

// Optional explicit integration mode. Only this mode briefly activates a small
// test-owned window; normal range tests above never change Windows foreground.
// The Python driver uses production tsf_bridge.Client against the real DLL.
static constexpr UINT kIpcReport = WM_APP + 20;
static constexpr UINT kIpcStop = WM_APP + 21;
static constexpr UINT kIpcExternalChange = WM_APP + 22;
static LRESULT CALLBACK IpcWindowProc(HWND window,UINT message,WPARAM wp,LPARAM lp){
    auto fixture=reinterpret_cast<Fixture*>(GetWindowLongPtrW(window,GWLP_USERDATA));
    if(message==WM_NCCREATE){fixture=static_cast<Fixture*>(reinterpret_cast<CREATESTRUCTW*>(lp)->lpCreateParams);SetWindowLongPtrW(window,GWLP_USERDATA,reinterpret_cast<LONG_PTR>(fixture));}
    if(message==kIpcReport&&fixture){
        const bool first=fixture->store->text==L"앞 Hello \U0001F600 뒤"&&fixture->store->writes==1&&fixture->store->selected.acpStart==10&&fixture->store->selected.acpEnd==10;
        const bool second=fixture->store->text==L"Second \U0001F44B"&&fixture->store->writes==2&&fixture->store->selected.acpStart==9&&fixture->store->selected.acpEnd==9;
        const bool changed=fixture->store->text==L"Edited \U0001F44B"&&fixture->store->writes==2;
        std::cout<<"{\"stage\":"<<wp<<",\"first\":"<<(first?"true":"false")<<",\"second\":"<<(second?"true":"false")<<",\"changed\":"<<(changed?"true":"false")<<",\"writes\":"<<fixture->store->writes<<",\"caret\":"<<fixture->store->selected.acpEnd<<"}"<<std::endl;
        return 1;
    }
    if(message==kIpcExternalChange&&fixture){fixture->store->ExternalReplace(0,6,L"Edited");return 1;}
    if(message==kIpcStop||message==WM_CLOSE){PostQuitMessage(0);return 0;}
    if(message==WM_TIMER){PostQuitMessage(124);return 0;}
    return DefWindowProcW(window,message,wp,lp);
}
static int IpcHost(const wchar_t* dllPath){
    struct Module {HMODULE handle;~Module(){if(handle)FreeLibrary(handle);}} module{LoadLibraryExW(dllPath,nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_SYSTEM32)};
    Require(module.handle!=nullptr,"load production TSF DLL");
    using GetClass=HRESULT(STDAPICALLTYPE*)(REFCLSID,REFIID,void**);
    const auto getClass=reinterpret_cast<GetClass>(GetProcAddress(module.handle,"DllGetClassObject"));
    Require(getClass!=nullptr,"DLL factory export");
    Fixture fixture(L"앞 안녕하세요 뒤",2,7);
    struct ActiveService {ComPtr<ITfTextInputProcessorEx> value;~ActiveService(){if(value)value->Deactivate();}} service;
    ComPtr<IClassFactory> factory;
    Check(getClass(stoom::ServiceId,IID_IClassFactory,reinterpret_cast<void**>(factory.GetAddressOf())),"GetClassObject");
    Check(factory->CreateInstance(nullptr,IID_PPV_ARGS(&service.value)),"Create service");
    Check(service.value->ActivateEx(fixture.manager.Get(),fixture.client,0),"Activate production service");

    const HWND previous=GetForegroundWindow();
    struct OwnedWindow {HWND previous=nullptr;HWND window=nullptr;~OwnedWindow(){
        const bool wasForeground=window&&GetForegroundWindow()==window;
        if(window&&IsWindow(window))DestroyWindow(window);
        if(wasForeground&&previous&&IsWindow(previous))SetForegroundWindow(previous);
    }} owned{previous,nullptr};
    WNDCLASSW wc{};wc.lpfnWndProc=IpcWindowProc;wc.lpszClassName=L"STOOM.Test.RealTsfHost";wc.hInstance=GetModuleHandleW(nullptr);
    Require(RegisterClassW(&wc)!=0,"register owned host window");
    owned.window=CreateWindowExW(WS_EX_TOOLWINDOW,wc.lpszClassName,L"STOOM TSF integration test (temporary)",WS_OVERLAPPED|WS_CAPTION|WS_SYSMENU,40,40,460,90,nullptr,nullptr,wc.hInstance,&fixture);
    Require(owned.window!=nullptr,"create owned host window");
    ShowWindow(owned.window,SW_SHOWNORMAL);SetForegroundWindow(owned.window);::SetFocus(owned.window);
    Check(fixture.manager->SetFocus(fixture.document.Get()),"focus own document");
    // Foreground changes may be queued. Give only our STA's window messages a
    // short opportunity to settle; do not attach input queues or synthesize keys.
    const auto focusDeadline=GetTickCount64()+300;
    while(GetForegroundWindow()!=owned.window&&GetTickCount64()<focusDeadline){
        MSG queued{};while(PeekMessageW(&queued,nullptr,0,0,PM_REMOVE)){TranslateMessage(&queued);DispatchMessageW(&queued);}
        Sleep(10);
    }
    GUITHREADINFO gui{sizeof(gui)};
    if(GetForegroundWindow()!=owned.window||!GetGUIThreadInfo(GetCurrentThreadId(),&gui)||gui.hwndFocus!=owned.window){
        std::cout<<"{\"skip\":true,\"reason\":\"Windows did not grant foreground to the owned test window\",\"foreground_matches\":"<<(GetForegroundWindow()==owned.window?"true":"false")<<",\"keyboard_matches\":"<<(gui.hwndFocus==owned.window?"true":"false")<<"}"<<std::endl;
        return 77;
    }
    SetTimer(owned.window,1,10000,nullptr);
    std::cout<<"{\"window\":"<<reinterpret_cast<uintptr_t>(owned.window)<<",\"thread\":"<<GetCurrentThreadId()<<",\"pid\":"<<GetCurrentProcessId()<<",\"native_service\":true}"<<std::endl;
    MSG message{};
    while(GetMessageW(&message,nullptr,0,0)>0){TranslateMessage(&message);DispatchMessageW(&message);}
    KillTimer(owned.window,1);
    if(message.wParam==124)return 124;
    return 0;
}

int wmain(int argc,wchar_t** argv){
    const HRESULT com=CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED);if(FAILED(com))return 2;
    int result=0;
    try{
        if(argc==3&&wcscmp(argv[1],L"--ipc")==0){result=IpcHost(argv[2]);CoUninitialize();return result;}
        const std::pair<const char*,std::function<void()>> tests[]={
            {"selected text / single SetText / caret",SelectionTest},
            {"current paragraph / preserve neighbours",ParagraphTest},
            {"read-only",ReadOnlyTest},
            {"password InputScope",[]{PasswordTest(IS_PASSWORD);}},
            {"private InputScope",[]{PasswordTest(IS_PRIVATE);}},
            {"numeric password InputScope",[]{PasswordTest(IS_NUMERIC_PASSWORD);}},
            {"numeric PIN InputScope",[]{PasswordTest(IS_NUMERIC_PIN);}},
            {"alphanumeric PIN InputScope",[]{PasswordTest(IS_ALPHANUMERIC_PIN);}},
            {"PIN setup InputScope",[]{PasswordTest(IS_ALPHANUMERIC_PIN_SET);}},
            {"source changed after capture",SourceChangedTest},
            {"selection changed after capture",SelectionChangedTest},
            {"composition active then complete",CompositionTest},
            {"write succeeded / caret refused",CaretFailureTest},
            {"password protection changed during translation",ProtectionChangedTest},
            {"oversized paragraph is not partially replaced",LongParagraphTest},
            {"same text in different context rejected",ForeignContextTest},
        };
        for(const auto& test:tests){test.second();std::cout<<"PASS: "<<test.first<<std::endl;}
        std::cout<<"Real msctf.dll range tests passed. No registration or external document access."<<std::endl;
    }catch(const std::exception&e){std::cerr<<"FAIL: "<<e.what()<<std::endl;result=1;}
    CoUninitialize();return result;
}
