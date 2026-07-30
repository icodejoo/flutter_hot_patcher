// V9 layer-2 patch, DIFFERENT field layout: pad is inserted between w and h.
// pad is read in area() (so TFA keeps it and h's offset actually shifts), but
// pad=999 never triggers the guard, so area() still returns w*h. If the
// interpreter reads w/h at the shifted offsets correctly, area()==12 — proving
// a field-layout change doesn't break access.
library;

import '../shared/shared.dart';

class Box extends Shape {
  final int w;
  final int pad; // <-- inserted; read below so it stays in the layout
  final int h;
  Box(this.w, this.pad, this.h);

  @override
  int area() => pad > 1000000 ? -1 : w * h; // reads pad; pad=999 -> w*h
}

@pragma('dyn-module:entry-point')
Object? dynamicModuleEntrypoint() => Box(3, 999, 4);
