part of 'app.dart';

@pragma('vm:never-inline')
int helperB(int x) => x * 3 + 5; // <-- was x*2+5, a real logic change staying in-place
