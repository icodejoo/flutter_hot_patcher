#include "dart_api.h"

namespace dart { namespace bin {
class Builtin {
public:
    static Dart_NativeFunction NativeLookup(Dart_Handle name, int argument_count, bool* auto_setup_scope);
    static const uint8_t* NativeSymbol(Dart_NativeFunction nf);
};
} }

namespace dart {
class BootstrapNatives {
public:
    static Dart_NativeFunction Lookup(Dart_Handle name, int argument_count, bool* auto_setup_scope);
};
}

extern "C" {
    Dart_NativeFunction builtin_native_lookup_shim(Dart_Handle name, int argument_count, bool* auto_setup_scope) {
        return dart::bin::Builtin::NativeLookup(name, argument_count, auto_setup_scope);
    }
    const uint8_t* builtin_native_symbol_shim(Dart_NativeFunction nf) {
        return dart::bin::Builtin::NativeSymbol(nf);
    }
    // Returns the actual BootstrapNatives::Lookup function pointer
    // so that Dart's IsBootstrapResolver check passes and native calls
    // go through BootstrapNativeCallWrapper (correct calling convention)
    Dart_NativeEntryResolver get_bootstrap_resolver(void) {
        return dart::BootstrapNatives::Lookup;
    }
}
