#include "range.h"
#include <initguid.h>
#include <inputscope.h>
#include <algorithm>
#include <cwctype>
#include <vector>

namespace stoom {
using Microsoft::WRL::ComPtr;
namespace {
constexpr HRESULT kChanged = HRESULT_FROM_WIN32(ERROR_REVISION_MISMATCH);

bool SameObject(IUnknown* a, IUnknown* b) {
    if (!a || !b) return false;
    ComPtr<IUnknown> left, right;
    return SUCCEEDED(a->QueryInterface(IID_PPV_ARGS(&left))) &&
           SUCCEEDED(b->QueryInterface(IID_PPV_ARGS(&right))) && left.Get() == right.Get();
}

HRESULT Selection(ITfContext* context, TfEditCookie cookie, ComPtr<ITfRange>& range,
                  TF_SELECTIONSTYLE& style) {
    TF_SELECTION selections[2]{};
    ULONG count = 0;
    HRESULT hr = context->GetSelection(cookie, 0, 2, selections, &count);
    if (SUCCEEDED(hr) && count == 1 && selections[0].range) {
        range.Attach(selections[0].range);
        selections[0].range = nullptr;
        style = selections[0].style;
        if (style.fInterimChar) hr = TF_E_LOCKED;
    } else if (SUCCEEDED(hr)) {
        hr = count == 0 ? TF_E_NOSELECTION : TF_E_FORMAT;
    }
    for (auto& selected : selections) if (selected.range) selected.range->Release();
    return hr;
}

// Read a clone so obtaining text never changes the real selection. MOVESTART
// and IsEmpty also detect a truncated or non-text range that GetText alone
// could otherwise report as a successful short read.
HRESULT ReadAll(ITfRange* range, TfEditCookie cookie, size_t limit, std::wstring& text) {
    text.clear();
    ComPtr<ITfRange> reader;
    HRESULT hr = range->Clone(&reader);
    if (FAILED(hr)) return hr;
    wchar_t buffer[1024];
    for (;;) {
        BOOL empty = FALSE;
        hr = reader->IsEmpty(cookie, &empty);
        if (FAILED(hr)) return hr;
        if (empty) return S_OK;
        ULONG count = 0;
        const ULONG capacity = static_cast<ULONG>((std::min)(size_t(1024), limit + 1 - text.size()));
        hr = reader->GetText(cookie, TF_TF_MOVESTART, buffer, capacity, &count);
        if (FAILED(hr)) return hr;
        if (count == 0 || count > capacity) return TF_E_FORMAT;
        text.append(buffer, count);
        if (text.size() > limit) return HRESULT_FROM_WIN32(ERROR_BUFFER_OVERFLOW);
    }
}

HRESULT ScopeValue(ITfReadOnlyProperty* property, ITfRange* range, TfEditCookie cookie) {
    VARIANT value;
    VariantInit(&value);
    HRESULT hr = property->GetValue(cookie, range, &value);
    if (SUCCEEDED(hr) && value.vt != VT_EMPTY) {
        if (value.vt != VT_UNKNOWN || !value.punkVal) hr = E_ACCESSDENIED;
        else {
            ComPtr<ITfInputScope> scope;
            hr = value.punkVal->QueryInterface(IID_PPV_ARGS(&scope));
            if (SUCCEEDED(hr)) {
                InputScope* scopes = nullptr;
                UINT count = 0;
                hr = scope->GetInputScopes(&scopes, &count);
                if (SUCCEEDED(hr) && count && !scopes) hr = E_ACCESSDENIED;
                if (SUCCEEDED(hr)) {
                    for (UINT i = 0; i < count; ++i) {
                        if (scopes[i] == IS_PASSWORD || scopes[i] == IS_PRIVATE ||
                            scopes[i] == IS_NUMERIC_PASSWORD || scopes[i] == IS_NUMERIC_PIN ||
                            scopes[i] == IS_ALPHANUMERIC_PIN || scopes[i] == IS_ALPHANUMERIC_PIN_SET) {
                            hr = E_ACCESSDENIED;
                            break;
                        }
                    }
                }
                CoTaskMemFree(scopes);
            }
        }
    }
    VariantClear(&value);
    return hr;
}

HRESULT CheckWritable(ITfContext* context, ITfRange* range, TfEditCookie cookie) {
    TF_STATUS status{};
    HRESULT hr = context->GetStatus(&status);
    if (FAILED(hr)) return hr;
    if (status.dwDynamicFlags & TS_SD_READONLY) return E_ACCESSDENIED;
    if (status.dwDynamicFlags & TS_SD_LOADING) return TF_E_LOCKED;

    ComPtr<ITfContextComposition> composition;
    hr = context->QueryInterface(IID_PPV_ARGS(&composition));
    if (FAILED(hr)) return hr;
    ComPtr<IEnumITfCompositionView> compositions;
    hr = composition->EnumCompositions(&compositions);
    if (FAILED(hr)) return hr;
    ITfCompositionView* active = nullptr;
    ULONG found = 0;
    hr = compositions->Next(1, &active, &found);
    if (active) active->Release();
    if (FAILED(hr)) return hr;
    if (found) return TF_E_LOCKED;

    // VT_EMPTY is the standard absence of an application scope. A declared
    // but unreadable scope is not assumed safe.
    ComPtr<ITfReadOnlyProperty> property;
    hr = context->GetAppProperty(GUID_PROP_INPUTSCOPE, &property);
    if (FAILED(hr) || !property) return FAILED(hr) ? hr : E_ACCESSDENIED;
    hr = ScopeValue(property.Get(), range, cookie);
    if (FAILED(hr)) return hr;
    ComPtr<IEnumTfRanges> regions;
    hr = property->EnumRanges(cookie, &regions, range);
    if (FAILED(hr)) return hr;
    if (!regions) return E_ACCESSDENIED;
    // Check each region as mixed scopes may have VT_EMPTY for the whole range.
    for (size_t i = 0; i <= kMaxSource; ++i) {
        ComPtr<ITfRange> region;
        ULONG fetched = 0;
        hr = regions->Next(1, &region, &fetched);
        if (FAILED(hr)) return hr;
        if (!fetched) return S_OK;
        if (!region) return E_ACCESSDENIED;
        hr = ScopeValue(property.Get(), region.Get(), cookie);
        if (FAILED(hr)) return hr;
    }
    return TF_E_FORMAT;
}

bool ValidText(const std::wstring& text, size_t limit) {
    if (text.empty() || text.size() > limit) return false;
    bool visible = false;
    for (size_t i = 0; i < text.size(); ++i) {
        const wchar_t ch = text[i];
        if (ch == 0 || ch == 0xfffc) return false;
        if (ch >= 0xd800 && ch <= 0xdbff) {
            if (++i == text.size() || text[i] < 0xdc00 || text[i] > 0xdfff) return false;
        } else if (ch >= 0xdc00 && ch <= 0xdfff) return false;
        if (!iswspace(ch)) visible = true;
    }
    return visible;
}
} // namespace

HRESULT Capture(ITfContext* context, TfEditCookie cookie, RangeSnapshot& output) {
    output = {};
    if (!context) return E_INVALIDARG;
    RangeSnapshot result;
    ComPtr<ITfRange> selection;
    HRESULT hr = Selection(context, cookie, selection, result.selection_style);
    if (FAILED(hr)) return hr;
    hr = CheckWritable(context, selection.Get(), cookie);
    if (FAILED(hr)) return hr;
    hr = selection->Clone(&result.selection);
    if (FAILED(hr)) return hr;
    hr = selection->Clone(&result.target);
    if (FAILED(hr)) return hr;
    BOOL empty = FALSE;
    hr = selection->IsEmpty(cookie, &empty);
    if (FAILED(hr)) return hr;
    if (empty) {
        constexpr LONG window = static_cast<LONG>(kMaxSource + 1);
        LONG left = 0, right = 0;
        hr = result.target->ShiftStart(cookie, -window, &left, nullptr);
        if (FAILED(hr)) return hr;
        hr = result.target->ShiftEnd(cookie, window, &right, nullptr);
        if (FAILED(hr)) return hr;
        if (left > 0 || left < -window || right < 0 || right > window) return TF_E_FORMAT;
        hr = CheckWritable(context, result.target.Get(), cookie);
        if (FAILED(hr)) return hr;
        std::wstring around;
        hr = ReadAll(result.target.Get(), cookie, 2 * window, around);
        if (FAILED(hr)) return hr;
        if (around.size() != static_cast<size_t>(right - left)) return TF_E_FORMAT;
        detail::ParagraphSpan span;
        if (!detail::Paragraph(around, static_cast<size_t>(-left), left > -window, right < window, span)) return S_FALSE;
        LONG moved = 0;
        hr = result.target->ShiftStart(cookie, static_cast<LONG>(span.start), &moved, nullptr);
        if (FAILED(hr)) return hr;
        if (moved != static_cast<LONG>(span.start)) return TF_E_FORMAT;
        const LONG tail = static_cast<LONG>(around.size() - span.end);
        hr = result.target->ShiftEnd(cookie, -tail, &moved, nullptr);
        if (FAILED(hr)) return hr;
        if (moved != -tail) return TF_E_FORMAT;
    }
    hr = CheckWritable(context, result.target.Get(), cookie);
    if (FAILED(hr)) return hr;
    hr = ReadAll(result.target.Get(), cookie, kMaxSource, result.original);
    if (FAILED(hr)) return hr;
    if (!ValidText(result.original, kMaxSource)) return S_FALSE;
    result.context = context;
    output = std::move(result);
    return S_OK;
}

HRESULT Validate(ITfContext* context, TfEditCookie cookie, const RangeSnapshot& snapshot) {
    if (!context || !snapshot.context || !snapshot.target || !snapshot.selection || snapshot.original.empty()) return E_INVALIDARG;
    if (!SameObject(context, snapshot.context.Get())) return kChanged;
    HRESULT hr = CheckWritable(context, snapshot.target.Get(), cookie);
    if (FAILED(hr)) return hr;
    ComPtr<ITfRange> current;
    TF_SELECTIONSTYLE style{};
    hr = Selection(context, cookie, current, style);
    if (FAILED(hr)) return hr;
    if (style.ase != snapshot.selection_style.ase) return kChanged;
    LONG start = 0, end = 0;
    hr = current->CompareStart(cookie, snapshot.selection.Get(), TF_ANCHOR_START, &start);
    if (FAILED(hr)) return hr;
    hr = current->CompareEnd(cookie, snapshot.selection.Get(), TF_ANCHOR_END, &end);
    if (FAILED(hr)) return hr;
    if (start || end) return kChanged;
    std::wstring text;
    hr = ReadAll(snapshot.target.Get(), cookie, kMaxSource, text);
    if (FAILED(hr)) return hr;
    return text == snapshot.original ? S_OK : kChanged;
}

HRESULT Apply(ITfContext* context, TfEditCookie cookie, const RangeSnapshot& snapshot,
              const std::wstring& replacement, const std::function<bool()>& before_write) {
    if (!ValidText(replacement, kMaxReplacement)) return E_INVALIDARG;
    HRESULT hr = Validate(context, cookie, snapshot);
    if (hr != S_OK) return hr;
    // Allocate the caret range before writing. SetText extends/retracts the
    // target's end to enclose the inserted text.
    ComPtr<ITfRange> caret;
    hr = snapshot.target->Clone(&caret);
    if (FAILED(hr)) return hr;
    hr = snapshot.target->SetGravity(cookie, TF_GRAVITY_BACKWARD, TF_GRAVITY_FORWARD);
    if (FAILED(hr)) return hr;
    if (before_write && !before_write()) return HRESULT_FROM_WIN32(ERROR_CANCELLED);
    hr = snapshot.target->SetText(cookie, TF_ST_CORRECTION, replacement.data(), static_cast<LONG>(replacement.size()));
    if (FAILED(hr)) return hr;
    hr = caret->ShiftEndToRange(cookie, snapshot.target.Get(), TF_ANCHOR_END);
    if (FAILED(hr)) return kAppliedCaretUnavailable;
    hr = caret->Collapse(cookie, TF_ANCHOR_END);
    if (FAILED(hr)) return kAppliedCaretUnavailable;
    TF_SELECTION selection{caret.Get(), {TF_AE_NONE, FALSE}};
    hr = context->SetSelection(cookie, 1, &selection);
    return SUCCEEDED(hr) ? S_OK : kAppliedCaretUnavailable;
}
} // namespace stoom
