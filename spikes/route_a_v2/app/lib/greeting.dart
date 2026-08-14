/// The patchable seam.
///
/// A dynamic module cannot replace an already-AOT-compiled function body, so
/// the app routes through an indirection that a module is allowed to write to.
/// Everything reachable from here must be listed in `dynamic_interface.yaml`.
library;

String Function() impl = () => 'BASELINE';

String greet() => impl();
