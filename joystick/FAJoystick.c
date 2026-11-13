#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>
#include <stdlib.h>
#include <string.h>

typedef MMRESULT (WINAPI *joy_get_pos_fn)(UINT_PTR, LPJOYINFO);
typedef MMRESULT (WINAPI *joy_get_pos_ex_fn)(UINT, LPJOYINFOEX);
typedef MMRESULT (WINAPI *joy_get_devcaps_a_fn)(UINT_PTR, LPJOYCAPSA, UINT);

static joy_get_pos_fn real_joy_get_pos;
static joy_get_pos_ex_fn real_joy_get_pos_ex;
static joy_get_devcaps_a_fn real_joy_get_devcaps_a;

static const DWORD axis_flags[6] = {
    JOY_RETURNX, JOY_RETURNY, JOY_RETURNZ,
    JOY_RETURNR, JOY_RETURNU, JOY_RETURNV
};

static const WORD axis_caps[6] = {
    0, 0, JOYCAPS_HASZ, JOYCAPS_HASR, JOYCAPS_HASU, JOYCAPS_HASV
};

static BYTE axis_sources[6] = {0, 1, 3, 2, 4, 5};
static BOOL inverted_axes[6];
static BYTE button_sources[32] = {
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16,
    17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32
};
static volatile LONG config_state;
static volatile LONG warning_shown;
static char config_path[MAX_PATH];

static int axis_index(const char *name)
{
    if (!lstrcmpiA(name, "X")) return 0;
    if (!lstrcmpiA(name, "Y")) return 1;
    if (!lstrcmpiA(name, "Z")) return 2;
    if (!lstrcmpiA(name, "R") || !lstrcmpiA(name, "RX")) return 3;
    if (!lstrcmpiA(name, "U")) return 4;
    if (!lstrcmpiA(name, "V")) return 5;
    return -1;
}

static void trim_token(char *token)
{
    char *start = token;
    char *end;

    while (*start == ' ' || *start == '\t') ++start;
    if (start != token) memmove(token, start, strlen(start) + 1);
    end = token + strlen(token);
    while (end > token && (end[-1] == ' ' || end[-1] == '\t')) --end;
    *end = '\0';
}

static BOOL parse_axis_map(const char *text)
{
    char copy[128];
    char *cursor;
    int parsed[6];
    int count = 0;
    char *token;

    if (lstrlenA(text) >= (int)sizeof(copy)) return FALSE;
    lstrcpyA(copy, text);
    cursor = copy;

    while ((token = cursor) != NULL && count < 6) {
        char *comma = strchr(cursor, ',');
        int index;
        if (comma) {
            *comma = '\0';
            cursor = comma + 1;
        } else {
            cursor = NULL;
        }
        trim_token(token);
        index = axis_index(token);
        if (index < 0) return FALSE;
        parsed[count++] = index;
    }

    if (count != 6 || cursor != NULL) return FALSE;
    for (count = 0; count < 6; ++count) axis_sources[count] = (BYTE)parsed[count];
    return TRUE;
}

static BOOL parse_button_map(const char *text)
{
    char copy[160];
    char *cursor;
    BYTE parsed[32];
    int count = 0;

    for (count = 0; count < 32; ++count) parsed[count] = (BYTE)(count + 1);
    if (!text[0]) {
        memcpy(button_sources, parsed, sizeof(parsed));
        return TRUE;
    }
    if (lstrlenA(text) >= (int)sizeof(copy)) return FALSE;
    lstrcpyA(copy, text);
    cursor = copy;
    count = 0;

    while (cursor && *cursor && count < 32) {
        char *comma = strchr(cursor, ',');
        char *end;
        long value;
        if (comma) {
            *comma = '\0';
            end = comma + 1;
        } else {
            end = NULL;
        }
        trim_token(cursor);
        if (!cursor[0]) return FALSE;
        value = strtol(cursor, &cursor, 10);
        while (*cursor == ' ' || *cursor == '\t') ++cursor;
        if (*cursor || value < 0 || value > 32) return FALSE;
        parsed[count++] = (BYTE)value;
        cursor = end;
        if (cursor && !*cursor) return FALSE;
    }
    if (cursor && *cursor) return FALSE;
    memcpy(button_sources, parsed, sizeof(parsed));
    return TRUE;
}

static BOOL parse_inverted_axes(const char *text)
{
    char copy[128];
    char *cursor;
    BOOL parsed[6] = {FALSE, FALSE, FALSE, FALSE, FALSE, FALSE};

    if (!text[0]) {
        memcpy(inverted_axes, parsed, sizeof(parsed));
        return TRUE;
    }
    if (lstrlenA(text) >= (int)sizeof(copy)) return FALSE;
    lstrcpyA(copy, text);
    cursor = copy;

    while (cursor && *cursor) {
        char *comma = strchr(cursor, ',');
        int index;
        if (comma) {
            *comma = '\0';
        }
        trim_token(cursor);
        index = axis_index(cursor);
        if (index < 0) return FALSE;
        parsed[index] = TRUE;
        cursor = comma ? comma + 1 : NULL;
    }
    memcpy(inverted_axes, parsed, sizeof(parsed));
    return TRUE;
}

static void show_config_warning(const char *message)
{
    if (InterlockedCompareExchange(&warning_shown, 1, 0) == 0) {
        MessageBoxA(NULL, message, "FA joystick mapping", MB_OK | MB_ICONWARNING);
    }
}

static BOOL build_config_path(void)
{
    DWORD length = GetModuleFileNameA(NULL, config_path, sizeof(config_path));
    char *slash;

    if (!length || length >= sizeof(config_path)) return FALSE;
    slash = strrchr(config_path, '\\');
    if (!slash) slash = strrchr(config_path, '/');
    if (!slash) return FALSE;
    if ((size_t)(slash + 1 - config_path) + sizeof("FA-JOYSTICK.INI")
            > sizeof(config_path)) {
        return FALSE;
    }
    lstrcpyA(slash + 1, "FA-JOYSTICK.INI");
    return TRUE;
}

static void load_config(void)
{
    char value[160];
    BOOL valid = TRUE;

    if (!build_config_path()) {
        show_config_warning("Could not locate FA-JOYSTICK.INI beside FA.EXE.");
        return;
    }

    GetPrivateProfileStringA("Mapping", "AxisMap", "X,Y,R,Z,U,V",
                             value, sizeof(value), config_path);
    if (!parse_axis_map(value)) valid = FALSE;

    GetPrivateProfileStringA("Mapping", "InvertAxes", "",
                             value, sizeof(value), config_path);
    if (!parse_inverted_axes(value)) valid = FALSE;

    GetPrivateProfileStringA("Mapping", "ButtonMap", "",
                             value, sizeof(value), config_path);
    if (!parse_button_map(value)) valid = FALSE;

    if (!valid) {
        show_config_warning(
            "FA-JOYSTICK.INI contains an invalid mapping. "
            "Invalid entries are being ignored; run configure-joystick.sh "
            "to repair the file.");
    }
}

static void ensure_config(void)
{
    if (InterlockedCompareExchange(&config_state, 1, 0) == 0) {
        load_config();
        InterlockedExchange(&config_state, 2);
    } else {
        while (InterlockedCompareExchange(&config_state, 2, 2) != 2) Sleep(0);
    }
}

static DWORD get_ex_axis(const JOYINFOEX *info, int index)
{
    switch (index) {
    case 0: return info->dwXpos;
    case 1: return info->dwYpos;
    case 2: return info->dwZpos;
    case 3: return info->dwRpos;
    case 4: return info->dwUpos;
    default: return info->dwVpos;
    }
}

static void set_ex_axis(JOYINFOEX *info, int index, DWORD value)
{
    switch (index) {
    case 0: info->dwXpos = value; break;
    case 1: info->dwYpos = value; break;
    case 2: info->dwZpos = value; break;
    case 3: info->dwRpos = value; break;
    case 4: info->dwUpos = value; break;
    default: info->dwVpos = value; break;
    }
}

static WORD get_caps_min(const JOYCAPSA *caps, int index)
{
    switch (index) {
    case 0: return caps->wXmin;
    case 1: return caps->wYmin;
    case 2: return caps->wZmin;
    case 3: return caps->wRmin;
    case 4: return caps->wUmin;
    default: return caps->wVmin;
    }
}

static WORD get_caps_max(const JOYCAPSA *caps, int index)
{
    switch (index) {
    case 0: return caps->wXmax;
    case 1: return caps->wYmax;
    case 2: return caps->wZmax;
    case 3: return caps->wRmax;
    case 4: return caps->wUmax;
    default: return caps->wVmax;
    }
}

static void remap_buttons(DWORD *buttons, DWORD *button_number)
{
    DWORD physical = *buttons;
    DWORD remapped = 0;
    DWORD i;

    for (i = 0; i < 32; ++i) {
        BYTE source = button_sources[i];
        if (source && (physical & (1UL << (source - 1)))) {
            remapped |= 1UL << i;
        }
    }
    *buttons = remapped;

    if (*button_number > 0 && *button_number <= 32) {
        DWORD source_button = *button_number;
        *button_number = 0;
        for (i = 0; i < 32; ++i) {
            if (button_sources[i] == source_button) {
                *button_number = i + 1;
                break;
            }
        }
    }
}

static void remap_ex_state(UINT_PTR device, JOYINFOEX *info, DWORD requested_flags)
{
    JOYINFOEX physical = *info;
    JOYCAPSA caps;
    BOOL have_caps = real_joy_get_devcaps_a
        && real_joy_get_devcaps_a(device, &caps, sizeof(caps)) == JOYERR_NOERROR;
    int i;

    for (i = 0; i < 6; ++i) {
        DWORD value;
        if (!(requested_flags & axis_flags[i])) continue;
        value = get_ex_axis(&physical, axis_sources[i]);
        if (inverted_axes[i]) {
            if (have_caps) {
                DWORD minimum = get_caps_min(&caps, axis_sources[i]);
                DWORD maximum = get_caps_max(&caps, axis_sources[i]);
                if (value < minimum) value = minimum;
                if (value > maximum) value = maximum;
                value = minimum + maximum - value;
            } else {
                show_config_warning(
                    "Could not read joystick axis ranges needed for inversion.");
            }
        }
        set_ex_axis(info, i, value);
    }

    if (requested_flags & JOY_RETURNBUTTONS) {
        remap_buttons(&info->dwButtons, &info->dwButtonNumber);
    }
    info->dwFlags = requested_flags;
}

static DWORD requested_source_flags(DWORD requested_flags)
{
    DWORD flags = requested_flags;
    int i;

    for (i = 0; i < 6; ++i) {
        if (requested_flags & axis_flags[i]) {
            flags |= axis_flags[axis_sources[i]];
        }
    }
    return flags;
}

static BOOL replace_import(DWORD *slot, DWORD replacement)
{
    DWORD old_protection;
    if (!VirtualProtect(slot, sizeof(*slot), PAGE_READWRITE, &old_protection)) {
        return FALSE;
    }
    *slot = replacement;
    if (!VirtualProtect(slot, sizeof(*slot), old_protection, &old_protection)) {
        return FALSE;
    }
    return TRUE;
}

static WORD get_joy_axis(const JOYINFO *info, int index)
{
    switch (index) {
    case 0: return info->wXpos;
    case 1: return info->wYpos;
    default: return info->wZpos;
    }
}

static void set_joy_axis(JOYINFO *info, int index, WORD value)
{
    switch (index) {
    case 0: info->wXpos = value; break;
    case 1: info->wYpos = value; break;
    default: info->wZpos = value; break;
    }
}

static BOOL joy_pos_needs_extended_state(void)
{
    int i;
    for (i = 0; i < 3; ++i) {
        if (axis_sources[i] >= 3 || inverted_axes[i]) return TRUE;
    }
    return FALSE;
}

static MMRESULT WINAPI mapped_joy_get_pos_ex(UINT device, LPJOYINFOEX info)
{
    DWORD requested_flags;
    MMRESULT result;

    if (!info || info->dwSize < sizeof(*info)) return JOYERR_PARMS;
    ensure_config();
    if (!real_joy_get_pos_ex) return MMSYSERR_INVALPARAM;
    requested_flags = info->dwFlags;
    info->dwFlags = requested_source_flags(requested_flags);
    result = real_joy_get_pos_ex(device, info);
    info->dwFlags = requested_flags;
    if (result == JOYERR_NOERROR) remap_ex_state(device, info, requested_flags);
    return result;
}

static MMRESULT WINAPI mapped_joy_get_pos(UINT_PTR device, LPJOYINFO info)
{
    JOYINFO physical;
    MMRESULT result;

    ensure_config();
    if (!real_joy_get_pos || !info) return MMSYSERR_INVALPARAM;
    result = real_joy_get_pos(device, &physical);
    if (result != JOYERR_NOERROR) return result;

    if (joy_pos_needs_extended_state() && real_joy_get_pos_ex) {
        JOYINFOEX extended;
        extended.dwSize = sizeof(extended);
        extended.dwFlags = JOY_RETURNX | JOY_RETURNY | JOY_RETURNZ | JOY_RETURNR
                         | JOY_RETURNU | JOY_RETURNV | JOY_RETURNBUTTONS;
        if (real_joy_get_pos_ex((UINT)device, &extended) == JOYERR_NOERROR) {
            remap_ex_state(device, &extended, extended.dwFlags);
            info->wXpos = (WORD)extended.dwXpos;
            info->wYpos = (WORD)extended.dwYpos;
            info->wZpos = (WORD)extended.dwZpos;
            info->wButtons = (WORD)extended.dwButtons;
            return result;
        }
        show_config_warning(
            "Could not read extended joystick axes needed by the configured mapping.");
    }

    {
        JOYCAPSA caps;
        BOOL have_caps = real_joy_get_devcaps_a
            && real_joy_get_devcaps_a(device, &caps, sizeof(caps)) == JOYERR_NOERROR;
        int i;
        JOYINFO mapped = physical;
        for (i = 0; i < 3; ++i) {
            int source = axis_sources[i];
            WORD value;
            if (source > 2) continue;
            value = get_joy_axis(&physical, source);
            if (inverted_axes[i] && have_caps) {
                DWORD minimum = get_caps_min(&caps, source);
                DWORD maximum = get_caps_max(&caps, source);
                if (value < minimum) value = (WORD)minimum;
                if (value > maximum) value = (WORD)maximum;
                value = (WORD)(minimum + maximum - value);
            }
            set_joy_axis(&mapped, i, value);
        }
        {
            DWORD buttons = physical.wButtons;
            DWORD button_number = 0;
            remap_buttons(&buttons, &button_number);
            mapped.wButtons = (WORD)buttons;
        }
        *info = mapped;
    }
    return result;
}

static MMRESULT WINAPI mapped_joy_get_devcaps_a(
    UINT_PTR device, LPJOYCAPSA caps, UINT size)
{
    JOYCAPSA physical;
    MMRESULT result;
    int i;

    ensure_config();
    if (!real_joy_get_devcaps_a || !caps) return MMSYSERR_INVALPARAM;
    if (size < sizeof(physical)) return MMSYSERR_INVALPARAM;
    result = real_joy_get_devcaps_a(device, &physical, sizeof(physical));
    if (result != JOYERR_NOERROR) return result;

    *caps = physical;
    for (i = 0; i < 6; ++i) {
        WORD minimum = get_caps_min(&physical, axis_sources[i]);
        WORD maximum = get_caps_max(&physical, axis_sources[i]);
        switch (i) {
        case 0: caps->wXmin = minimum; caps->wXmax = maximum; break;
        case 1: caps->wYmin = minimum; caps->wYmax = maximum; break;
        case 2: caps->wZmin = minimum; caps->wZmax = maximum; break;
        case 3: caps->wRmin = minimum; caps->wRmax = maximum; break;
        case 4: caps->wUmin = minimum; caps->wUmax = maximum; break;
        default: caps->wVmin = minimum; caps->wVmax = maximum; break;
        }
    }
    {
        WORD remapped_caps = physical.wCaps
            & (WORD)~(JOYCAPS_HASZ | JOYCAPS_HASR | JOYCAPS_HASU | JOYCAPS_HASV);
        for (i = 2; i < 6; ++i) {
            int source = axis_sources[i];
            if (source < 2 || (physical.wCaps & axis_caps[source])) {
                remapped_caps |= axis_caps[i];
            }
        }
        caps->wCaps = remapped_caps;
    }
    if (size < sizeof(physical)) return MMSYSERR_INVALPARAM;
    return JOYERR_NOERROR;
}

static BOOL patch_imports(void)
{
    BYTE *base = (BYTE *)GetModuleHandleA(NULL);
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
    IMAGE_NT_HEADERS32 *nt;
    IMAGE_DATA_DIRECTORY directory;
    IMAGE_IMPORT_DESCRIPTOR *descriptor;
    DWORD *pos_get_pos = NULL;
    DWORD *pos_get_pos_ex = NULL;
    DWORD *pos_get_devcaps = NULL;
    joy_get_pos_fn original_get_pos = NULL;
    joy_get_pos_ex_fn original_get_pos_ex = NULL;
    joy_get_devcaps_a_fn original_get_devcaps = NULL;

    if (!base || dos->e_magic != IMAGE_DOS_SIGNATURE) return FALSE;
    nt = (IMAGE_NT_HEADERS32 *)(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return FALSE;
    directory = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!directory.VirtualAddress) return FALSE;

    descriptor = (IMAGE_IMPORT_DESCRIPTOR *)(base + directory.VirtualAddress);
    for (; descriptor->Name; ++descriptor) {
        const char *dll_name = (const char *)(base + descriptor->Name);
        IMAGE_THUNK_DATA32 *names;
        IMAGE_THUNK_DATA32 *iat;

        if (lstrcmpiA(dll_name, "WINMM.dll")) continue;
        names = (IMAGE_THUNK_DATA32 *)(base
            + (descriptor->OriginalFirstThunk
                ? descriptor->OriginalFirstThunk : descriptor->FirstThunk));
        iat = (IMAGE_THUNK_DATA32 *)(base + descriptor->FirstThunk);
        for (; names->u1.AddressOfData; ++names, ++iat) {
            IMAGE_IMPORT_BY_NAME *import_name;
            DWORD *slot = &iat->u1.Function;
            if (IMAGE_SNAP_BY_ORDINAL32(names->u1.Ordinal)) continue;
            import_name = (IMAGE_IMPORT_BY_NAME *)(base + names->u1.AddressOfData);
            if (!lstrcmpiA((const char *)import_name->Name, "joyGetPos")) {
                pos_get_pos = slot;
                original_get_pos = (joy_get_pos_fn)(ULONG_PTR)*slot;
            } else if (!lstrcmpiA((const char *)import_name->Name, "joyGetPosEx")) {
                pos_get_pos_ex = slot;
                original_get_pos_ex = (joy_get_pos_ex_fn)(ULONG_PTR)*slot;
            } else if (!lstrcmpiA((const char *)import_name->Name, "joyGetDevCapsA")) {
                pos_get_devcaps = slot;
                original_get_devcaps = (joy_get_devcaps_a_fn)(ULONG_PTR)*slot;
            }
        }
        break;
    }

    if (!pos_get_pos || !pos_get_pos_ex || !pos_get_devcaps
            || !original_get_pos || !original_get_pos_ex || !original_get_devcaps) {
        OutputDebugStringA("FAJoystick: expected WINMM joystick imports were not found.");
        return FALSE;
    }

    real_joy_get_pos = original_get_pos;
    real_joy_get_pos_ex = original_get_pos_ex;
    real_joy_get_devcaps_a = original_get_devcaps;
    if (!replace_import(pos_get_pos, (DWORD)(ULONG_PTR)mapped_joy_get_pos)
            || !replace_import(pos_get_pos_ex, (DWORD)(ULONG_PTR)mapped_joy_get_pos_ex)
            || !replace_import(pos_get_devcaps,
                               (DWORD)(ULONG_PTR)mapped_joy_get_devcaps_a)) {
        OutputDebugStringA("FAJoystick: could not update the executable import table.");
        return FALSE;
    }
    return TRUE;
}

void __cdecl FAJoystick_Initialize(void)
{
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(instance);
        if (!patch_imports()) {
            OutputDebugStringA("FAJoystick: joystick remapping is unavailable.");
        }
    }
    return TRUE;
}
