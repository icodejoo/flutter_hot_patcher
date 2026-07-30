// V9 layer-2 (runtime) shared interface, known to the host AOT app. The host
// only ever touches Box through this virtual interface (area()), never its
// concrete fields — that virtual-call boundary is exactly what keeps a
// field-layout change from corrupting memory (SPEC §5).
library;

abstract class Shape {
  int area();
}
