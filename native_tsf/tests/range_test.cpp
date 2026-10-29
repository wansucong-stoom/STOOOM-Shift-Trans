// Deterministic COM-provider tests. These never inspect or modify a live app.
#include "../range.h"
#include <inputscope.h>
#include <wrl/implements.h>
#include <algorithm>
#include <cassert>
#include <cstdio>
#include <vector>

using Microsoft::WRL::ComPtr;
using Microsoft::WRL::Make;
using Microsoft::WRL::RuntimeClass;
using Microsoft::WRL::RuntimeClassFlags;
using Microsoft::WRL::ClassicCom;

struct Document {
    std::wstring text = L"앞 문단\r\n안녕하세요\r\n뒷 문단";
    LONG selection_start = 7, selection_end = 7;
    DWORD status = 0;
    bool composing = false, password = false, private_scope = false;
    bool refuse_caret = false, short_reads = false, no_progress = false;
    bool disjoint = false;
    InputScope declared_scope = IS_DEFAULT;
    int writes = 0, selections = 0;
};

class Range final : public RuntimeClass<RuntimeClassFlags<ClassicCom>, ITfRange> {
public:
    Document* doc;
    LONG start, end;
    Range(Document* d, LONG s, LONG e) : doc(d), start(s), end(e) {}
    HRESULT STDMETHODCALLTYPE GetText(TfEditCookie, DWORD flags, WCHAR* out, ULONG cap, ULONG* count) override {
        if (doc->no_progress) { *count = 0; return S_OK; }
        *count = (std::min)(cap, static_cast<ULONG>((std::max)(0L, end - start)));
        if (doc->short_reads) *count = (std::min)(*count, 2UL);
        std::copy_n(doc->text.data() + start, *count, out);
        if (flags & TF_TF_MOVESTART) start += *count;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE SetText(TfEditCookie, DWORD flags, const WCHAR* text, LONG length) override {
        assert(flags == TF_ST_CORRECTION);
        doc->text.replace(start, end - start, text, length);
        end = start + length;
        ++doc->writes;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE GetFormattedText(TfEditCookie, IDataObject**) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE GetEmbedded(TfEditCookie, REFGUID, REFIID, IUnknown**) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE InsertEmbedded(TfEditCookie, DWORD, IDataObject*) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE ShiftStart(TfEditCookie, LONG n, LONG* moved, const TF_HALTCOND*) override {
        LONG next = std::clamp(start + n, 0L, end); *moved = next - start; start = next; return S_OK;
    }
    HRESULT STDMETHODCALLTYPE ShiftEnd(TfEditCookie, LONG n, LONG* moved, const TF_HALTCOND*) override {
        LONG next = std::clamp(end + n, start, static_cast<LONG>(doc->text.size())); *moved = next - end; end = next; return S_OK;
    }
    HRESULT STDMETHODCALLTYPE ShiftStartToRange(TfEditCookie, ITfRange* other, TfAnchor anchor) override {
        Range* r = static_cast<Range*>(other); start = anchor == TF_ANCHOR_START ? r->start : r->end; return S_OK;
    }
    HRESULT STDMETHODCALLTYPE ShiftEndToRange(TfEditCookie, ITfRange* other, TfAnchor anchor) override {
        Range* r = static_cast<Range*>(other); end = anchor == TF_ANCHOR_START ? r->start : r->end; return S_OK;
    }
    HRESULT STDMETHODCALLTYPE ShiftStartRegion(TfEditCookie, TfShiftDir, BOOL*) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE ShiftEndRegion(TfEditCookie, TfShiftDir, BOOL*) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE IsEmpty(TfEditCookie, BOOL* empty) override { *empty = start == end; return S_OK; }
    HRESULT STDMETHODCALLTYPE Collapse(TfEditCookie, TfAnchor anchor) override {
        if (anchor == TF_ANCHOR_START) end = start; else start = end;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE IsEqualStart(TfEditCookie, ITfRange*, TfAnchor, BOOL*) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE IsEqualEnd(TfEditCookie, ITfRange*, TfAnchor, BOOL*) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE CompareStart(TfEditCookie, ITfRange* other, TfAnchor anchor, LONG* result) override {
        Range* r = static_cast<Range*>(other); *result = start - (anchor == TF_ANCHOR_START ? r->start : r->end); return S_OK;
    }
    HRESULT STDMETHODCALLTYPE CompareEnd(TfEditCookie, ITfRange* other, TfAnchor anchor, LONG* result) override {
        Range* r = static_cast<Range*>(other); *result = end - (anchor == TF_ANCHOR_START ? r->start : r->end); return S_OK;
    }
    HRESULT STDMETHODCALLTYPE AdjustForInsert(TfEditCookie, ULONG, BOOL*) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE GetGravity(TfGravity* a, TfGravity* b) override { *a = TF_GRAVITY_BACKWARD; *b = TF_GRAVITY_FORWARD; return S_OK; }
    HRESULT STDMETHODCALLTYPE SetGravity(TfEditCookie, TfGravity, TfGravity) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE Clone(ITfRange** out) override { return Make<Range>(doc, start, end).CopyTo(out); }
    HRESULT STDMETHODCALLTYPE GetContext(ITfContext**) override { return E_NOTIMPL; }
};

class Scope final : public RuntimeClass<RuntimeClassFlags<ClassicCom>, ITfInputScope> {
    InputScope value;
public:
    explicit Scope(InputScope v) : value(v) {}
    HRESULT STDMETHODCALLTYPE GetInputScopes(InputScope** out, UINT* count) override {
        *out = static_cast<InputScope*>(CoTaskMemAlloc(sizeof(InputScope)));
        if (!*out) return E_OUTOFMEMORY;
        **out = value; *count = 1; return S_OK;
    }
    HRESULT STDMETHODCALLTYPE GetPhrase(BSTR**, UINT*) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE GetRegularExpression(BSTR*) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE GetSRGS(BSTR*) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE GetXML(BSTR*) override { return E_NOTIMPL; }
};

class EmptyRanges final : public RuntimeClass<RuntimeClassFlags<ClassicCom>, IEnumTfRanges> {
public:
    HRESULT STDMETHODCALLTYPE Clone(IEnumTfRanges** out) override { return Make<EmptyRanges>().CopyTo(out); }
    HRESULT STDMETHODCALLTYPE Next(ULONG, ITfRange**, ULONG* count) override { *count = 0; return S_FALSE; }
    HRESULT STDMETHODCALLTYPE Reset() override { return S_OK; }
    HRESULT STDMETHODCALLTYPE Skip(ULONG) override { return S_FALSE; }
};

class Property final : public RuntimeClass<RuntimeClassFlags<ClassicCom>, ITfReadOnlyProperty> {
    Document* doc;
public:
    explicit Property(Document* d) : doc(d) {}
    HRESULT STDMETHODCALLTYPE GetType(GUID* out) override { *out = GUID_PROP_INPUTSCOPE; return S_OK; }
    HRESULT STDMETHODCALLTYPE EnumRanges(TfEditCookie, IEnumTfRanges** out, ITfRange*) override { return Make<EmptyRanges>().CopyTo(out); }
    HRESULT STDMETHODCALLTYPE GetValue(TfEditCookie, ITfRange*, VARIANT* output) override {
        VariantInit(output);
        if (doc->password || doc->private_scope || doc->declared_scope != IS_DEFAULT) {
            auto scope = Make<Scope>(doc->password ? IS_PASSWORD : (doc->private_scope ? IS_PRIVATE : doc->declared_scope));
            output->vt = VT_UNKNOWN;
            return scope.CopyTo(&output->punkVal);
        }
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE GetContext(ITfContext**) override { return E_NOTIMPL; }
};

class CompositionView final : public RuntimeClass<RuntimeClassFlags<ClassicCom>, ITfCompositionView> {
public:
    HRESULT STDMETHODCALLTYPE GetOwnerClsid(CLSID* out) override { *out = CLSID_NULL; return S_OK; }
    HRESULT STDMETHODCALLTYPE GetRange(ITfRange**) override { return E_NOTIMPL; }
};

class Compositions final : public RuntimeClass<RuntimeClassFlags<ClassicCom>, IEnumITfCompositionView> {
    bool active;
public:
    explicit Compositions(bool a) : active(a) {}
    HRESULT STDMETHODCALLTYPE Clone(IEnumITfCompositionView** out) override { return Make<Compositions>(active).CopyTo(out); }
    HRESULT STDMETHODCALLTYPE Next(ULONG count, ITfCompositionView** out, ULONG* fetched) override {
        if (count && active) { *fetched = 1; active = false; return Make<CompositionView>().CopyTo(out); }
        *fetched = 0; return S_FALSE;
    }
    HRESULT STDMETHODCALLTYPE Reset() override { return S_OK; }
    HRESULT STDMETHODCALLTYPE Skip(ULONG) override { active = false; return S_FALSE; }
};

class Context final : public RuntimeClass<RuntimeClassFlags<ClassicCom>, ITfContext, ITfContextComposition> {
public:
    Document doc;
    HRESULT STDMETHODCALLTYPE RequestEditSession(TfClientId, ITfEditSession*, DWORD, HRESULT*) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE InWriteSession(TfClientId, BOOL*) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE GetSelection(TfEditCookie, ULONG, ULONG count, TF_SELECTION* out, ULONG* fetched) override {
        assert(count >= 2);
        *fetched = doc.disjoint ? 2UL : 1UL;
        out[0].style = {TF_AE_NONE, FALSE};
        HRESULT hr = Make<Range>(&doc, doc.selection_start, doc.selection_end).CopyTo(&out[0].range);
        if (doc.disjoint) {
            out[1].style = {TF_AE_NONE, FALSE};
            Make<Range>(&doc, 0, 1).CopyTo(&out[1].range);
        }
        return hr;
    }
    HRESULT STDMETHODCALLTYPE SetSelection(TfEditCookie, ULONG count, const TF_SELECTION* in) override {
        assert(count == 1);
        if (doc.refuse_caret) return E_FAIL;
        auto range = static_cast<Range*>(in[0].range);
        doc.selection_start = range->start; doc.selection_end = range->end;
        ++doc.selections; return S_OK;
    }
    HRESULT STDMETHODCALLTYPE GetStart(TfEditCookie, ITfRange** out) override { return Make<Range>(&doc, 0, 0).CopyTo(out); }
    HRESULT STDMETHODCALLTYPE GetEnd(TfEditCookie, ITfRange** out) override {
        LONG end = static_cast<LONG>(doc.text.size()); return Make<Range>(&doc, end, end).CopyTo(out);
    }
    HRESULT STDMETHODCALLTYPE GetActiveView(ITfContextView**) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE EnumViews(IEnumTfContextViews**) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE GetStatus(TF_STATUS* status) override { *status = {}; status->dwDynamicFlags = doc.status; return S_OK; }
    HRESULT STDMETHODCALLTYPE GetProperty(REFGUID, ITfProperty**) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE GetAppProperty(REFGUID, ITfReadOnlyProperty** out) override { return Make<Property>(&doc).CopyTo(out); }
    HRESULT STDMETHODCALLTYPE TrackProperties(const GUID**, ULONG, const GUID**, ULONG, ITfReadOnlyProperty**) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE EnumProperties(IEnumTfProperties**) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE GetDocumentMgr(ITfDocumentMgr**) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE CreateRangeBackup(TfEditCookie, ITfRange*, ITfRangeBackup**) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE StartComposition(TfEditCookie, ITfRange*, ITfCompositionSink*, ITfComposition**) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE EnumCompositions(IEnumITfCompositionView** out) override { return Make<Compositions>(doc.composing).CopyTo(out); }
    HRESULT STDMETHODCALLTYPE FindComposition(TfEditCookie, ITfRange*, IEnumITfCompositionView**) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE TakeOwnership(TfEditCookie, ITfCompositionView*, ITfCompositionSink*, ITfComposition**) override { return E_NOTIMPL; }
};

int main() {
    using namespace stoom;
    constexpr TfEditCookie cookie = 12;
    {
        auto context = Make<Context>();
        RangeSnapshot snap;
        assert(Capture(context.Get(), cookie, snap) == S_OK);
        assert(snap.original == L"안녕하세요");
        assert(context->doc.selections == 0 && context->doc.writes == 0);
        assert(Apply(context.Get(), cookie, snap, L"Hello") == S_OK);
        assert(context->doc.text == L"앞 문단\r\nHello\r\n뒷 문단");
        assert(context->doc.selection_start == 11 && context->doc.selection_end == 11);
        assert(context->doc.writes == 1);
    }
    {
        auto context = Make<Context>();
        context->doc.selection_start = 6; context->doc.selection_end = 8;
        RangeSnapshot snap;
        assert(Capture(context.Get(), cookie, snap) == S_OK);
        assert(snap.original == L"안녕");
        assert(Apply(context.Get(), cookie, snap, L"Hi") == S_OK);
        assert(context->doc.text == L"앞 문단\r\nHi하세요\r\n뒷 문단");
    }
    for (int mode = 0; mode != 6; ++mode) {
        auto context = Make<Context>();
        RangeSnapshot snap;
        assert(Capture(context.Get(), cookie, snap) == S_OK);
        if (mode == 0) context->doc.text[7] = L'X';
        if (mode == 1) ++context->doc.selection_start;
        if (mode == 2) ++context->doc.selection_end;
        if (mode == 3) context->doc.password = true;
        if (mode == 4) context->doc.composing = true;
        if (mode == 5) context->doc.status = TS_SD_READONLY;
        assert(FAILED(Apply(context.Get(), cookie, snap, L"Hello")));
        assert(context->doc.writes == 0);
    }
    {
        auto context = Make<Context>();
        auto other = Make<Context>();
        RangeSnapshot snap;
        assert(Capture(context.Get(), cookie, snap) == S_OK);
        assert(FAILED(Apply(other.Get(), cookie, snap, L"Hello")));
        assert(context->doc.writes == 0 && other->doc.writes == 0);
    }
    for (int mode = 0; mode != 6; ++mode) {
        auto context = Make<Context>();
        if (mode == 0) context->doc.password = true;
        if (mode == 1) context->doc.private_scope = true;
        if (mode == 2) context->doc.composing = true;
        if (mode == 3) context->doc.status = TS_SD_READONLY;
        if (mode == 4) context->doc.disjoint = true;
        if (mode == 5) context->doc.no_progress = true;
        RangeSnapshot snap;
        assert(FAILED(Capture(context.Get(), cookie, snap)));
        assert(!snap.target && snap.original.empty());
    }
    for (InputScope scope : {IS_NUMERIC_PASSWORD, IS_NUMERIC_PIN, IS_ALPHANUMERIC_PIN, IS_ALPHANUMERIC_PIN_SET}) {
        auto context = Make<Context>();
        context->doc.declared_scope = scope;
        RangeSnapshot snap;
        assert(Capture(context.Get(), cookie, snap) == E_ACCESSDENIED);
    }
    {
        auto context = Make<Context>();
        context->doc.refuse_caret = true;
        RangeSnapshot snap;
        assert(Capture(context.Get(), cookie, snap) == S_OK);
        assert(Apply(context.Get(), cookie, snap, L"Hello") == kAppliedCaretUnavailable);
        assert(context->doc.writes == 1);
    }
    {
        auto context = Make<Context>();
        context->doc.short_reads = true;
        RangeSnapshot snap;
        assert(Capture(context.Get(), cookie, snap) == S_OK);
        assert(snap.original == L"안녕하세요");
        assert(Apply(context.Get(), cookie, snap, std::wstring(16001, L'x')) == E_INVALIDARG);
        assert(Apply(context.Get(), cookie, snap, std::wstring(1, wchar_t(0xd800))) == E_INVALIDARG);
        assert(Apply(context.Get(), cookie, snap, L"hello\xfffc") == E_INVALIDARG);
        assert(context->doc.writes == 0);
    }
    {
        auto context = Make<Context>();
        RangeSnapshot snap;
        assert(Capture(context.Get(), cookie, snap) == S_OK);
        int guard_calls = 0;
        assert(Apply(context.Get(), cookie, snap, L"Hello", [&] { ++guard_calls; return false; }) == HRESULT_FROM_WIN32(ERROR_CANCELLED));
        assert(guard_calls == 1 && context->doc.writes == 0);
    }
    for (const auto& source : {std::wstring(8001, L'x'), std::wstring(L"a\xfffc" L"b"), std::wstring(L"   ")}) {
        auto context = Make<Context>();
        context->doc.text = source;
        context->doc.selection_start = context->doc.selection_end = 1;
        RangeSnapshot snap;
        assert(Capture(context.Get(), cookie, snap) != S_OK);
    }
    for (LONG caret : {0L, 4000L, 8000L}) {
        auto context = Make<Context>();
        context->doc.text = std::wstring(8000, L'x');
        context->doc.selection_start = context->doc.selection_end = caret;
        RangeSnapshot snap;
        assert(Capture(context.Get(), cookie, snap) == S_OK);
        assert(snap.original.size() == 8000);
    }
    {
        auto context = Make<Context>();
        context->doc.text = L"hi \xd83d\xde00";
        context->doc.selection_start = context->doc.selection_end = 0;
        RangeSnapshot snap;
        assert(Capture(context.Get(), cookie, snap) == S_OK);
        assert(snap.original == context->doc.text);
    }
    {
        detail::ParagraphSpan span;
        assert(detail::Paragraph(L"first\r\nsecond\nthird", 7, true, true, span));
        assert(span.start == 7 && span.end == 13);
        assert(detail::Paragraph(L"first\r\nsecond", 6, true, true, span));
        assert(span.start == 0 && span.end == 5);
        assert(!detail::Paragraph(L"truncated", 3, false, true, span));
        assert(!detail::Paragraph(L"truncated", 3, true, false, span));
        assert(!detail::Paragraph(L"\r\n", 0, true, true, span));
        assert(detail::Paragraph(L"a\x2029z", 2, true, true, span));
        assert(span.start == 2 && span.end == 3);
    }
    puts("TSF range tests passed: selection/paragraph, exact replacement, caret, stale source/position/context, scopes, composition, bounds.");
}
