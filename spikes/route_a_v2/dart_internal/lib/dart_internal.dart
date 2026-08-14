/// Route-A loader shim.
///
/// `loadDynamicModule` lives in the platform-private library `dart:_internal`.
/// Normal app code cannot import it, but the CFE allowlist
/// (`pkg/kernel/lib/target/targets.dart:347`) makes an exception for packages
/// named `dart_internal` / `dynamic_modules`, so a thin path-dependency like
/// this one re-exports it to the app — including Flutter apps.
library;

import 'dart:typed_data' show Uint8List;
import 'dart:_internal' as internal;

/// Loads a KBC bytecode module and runs its `dyn-module:entry-point`.
Future<Object?> loadModuleFromBytes(Uint8List bytes) =>
    internal.loadDynamicModule(bytes: bytes);

/// Loads a KBC bytecode module from [uri] and runs its entry point.
Future<Object?> loadModuleFromUri(Uri uri) =>
    internal.loadDynamicModule(uri: uri);
