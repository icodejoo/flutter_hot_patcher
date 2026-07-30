// V9 layer-2 patch: defines Box, a class with NEW instance fields (w, h) not
// known to the host AOT app. The interpreter must allocate Box with the right
// layout and read w/h at the right offsets for area() to be correct.
library;

import '../shared/shared.dart';

class Box extends Shape {
  final int w;
  final int h;
  Box(this.w, this.h);

  @override
  int area() => w * h;
}

@pragma('dyn-module:entry-point')
Object? dynamicModuleEntrypoint() => Box(3, 4);
