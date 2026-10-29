#pragma once

#include <windows.h>
#include <msctf.h>
#include <wrl/client.h>
#include <string>
#include <string_view>
#include <functional>

namespace stoom {
constexpr size_t kMaxSource = 8000;
constexpr size_t kMaxReplacement = 16000;
// SetText succeeded, but the host refused the subsequent caret placement.
// This is a completed replacement: callers MUST NOT retry or fall back.
constexpr HRESULT kAppliedCaretUnavailable = MAKE_HRESULT(SEVERITY_SUCCESS, FACILITY_ITF, 0x0601);

struct RangeSnapshot {
    Microsoft::WRL::ComPtr<ITfContext> context;
    Microsoft::WRL::ComPtr<ITfRange> target;
    Microsoft::WRL::ComPtr<ITfRange> selection;
    std::wstring original;
    TF_SELECTIONSTYLE selection_style{TF_AE_NONE, FALSE};
};

// Must all run in an edit session on the context's original STA thread.
// Capture/Validate require READ; Apply requires READWRITE.
HRESULT Capture(ITfContext* context, TfEditCookie cookie, RangeSnapshot& output);
HRESULT Validate(ITfContext* context, TfEditCookie cookie, const RangeSnapshot& snapshot);
HRESULT Apply(ITfContext* context, TfEditCookie cookie, const RangeSnapshot& snapshot,
              const std::wstring& replacement, const std::function<bool()>& before_write = {});

namespace detail {
struct ParagraphSpan { size_t start = 0, end = 0; };
inline bool LineBreak(wchar_t ch) {
    return ch == L'\r' || ch == L'\n' || ch == 0x2028 || ch == 0x2029;
}
// The text is a bounded window around a collapsed caret. The caller supplies
// evidence that each edge is the document boundary, not just the buffer edge.
inline bool Paragraph(std::wstring_view text, size_t caret, bool at_start,
                      bool at_end, ParagraphSpan& span) {
    if (caret > text.size()) return false;
    // The interior of a CRLF belongs to its preceding paragraph.
    if (caret && caret < text.size() && text[caret] == L'\n' && text[caret - 1] == L'\r') --caret;
    span.start = caret;
    span.end = caret;
    while (span.start && !LineBreak(text[span.start - 1])) --span.start;
    while (span.end < text.size() && !LineBreak(text[span.end])) ++span.end;
    return (span.start || at_start) && (span.end < text.size() || at_end) &&
           span.end > span.start && span.end - span.start <= kMaxSource;
}
} // namespace detail
} // namespace stoom
