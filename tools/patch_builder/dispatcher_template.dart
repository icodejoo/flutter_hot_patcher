// Template for multi-function patches
// Usage: generate one dill per changed function group, with dispatcher
//
// CONSTRAINT: dyn-module entry-point must be a static NO-ARGUMENT method.
// Protocol: write target function name to _dispatchFn global, call dispatch(),
//           then read result from _dispatchResult global.
library hotpatch_patch;

// Private implementations (can have as many as needed)
// {{PRIVATE_IMPLS}}

// Shared state for no-arg dispatch protocol (host communicates via globals)
String _dispatchFn = '';
String _dispatchResult = '';

// Single entry-point dispatcher (no arguments — required by dart2bytecode)
@pragma('dyn-module:entry-point')
void dispatch() {
  final fn = _dispatchFn;
  // {{DISPATCH_TABLE}}
  _dispatchResult = '{"error":"unknown_fn:$fn"}';
}
