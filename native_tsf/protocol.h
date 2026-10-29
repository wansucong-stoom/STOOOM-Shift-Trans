#pragma once
#include <windows.h>
#include <cstdint>

namespace stoom {
inline constexpr uint32_t Magic = 0x53544636;
inline constexpr uint32_t ProtocolVersion = 1;
inline constexpr wchar_t WindowClass[] = L"STOOM.TextService.1";
inline constexpr wchar_t MappingPrefix[] = L"Local\\STOOM.TSF.";
inline constexpr GUID ServiceId = {0x89eb3b8d,0xa777,0x47d6,{0xa4,0xc2,0x1b,0x63,0x51,0x27,0x06,0xb8}};
inline constexpr GUID CategoryId = {0xaf214fea,0xca62,0x4bdd,{0xba,0xce,0x27,0x81,0x8b,0x40,0x56,0xdf}};
inline constexpr GUID ProfileId = {0x24279b83,0x68fb,0x49cd,{0x9d,0x44,0x39,0x54,0xb3,0xc8,0xa1,0x5a}};
enum Operation : uint32_t { CaptureOp=1, ApplyOp=2, CancelOp=3 };
// Fixed-width fields: the same layout is used by x86, x64, and Python.
#pragma pack(push, 8)
struct Packet {
    uint32_t magic, version, operation;
    int32_t status;
    uint64_t deadline, foreground, keyboard;
    uint32_t thread, client, length, complete;
    GUID snapshot;
    wchar_t text[16001];
};
struct Notice { uint32_t magic; wchar_t name[96]; };
#pragma pack(pop)
static_assert(offsetof(Packet, text)==72, "IPC layout changed");
static_assert(sizeof(Packet)==32080, "IPC size changed");
}
