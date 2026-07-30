// P2 Flutter widget sample — BASE. Covers StatelessWidget, StatefulWidget +
// build + setState, and a build-helper called directly (cascade). Compiled to a
// host-x64 AOT ELF (libapp.so) and diffed against patch/. The point: a widget
// code change is detected, its closure stays tiny, and the whole Flutter
// framework (thousands of functions) stays equivalent — not re-interpreted.
import 'package:flutter/widgets.dart';

// Build helper called directly by Tile.build -> changing it must cascade to
// Tile.build (condition 2), just like V6/V8.
@pragma('vm:never-inline')
int layoutMetric(int n) => n * 4 + 9;

class Tile extends StatelessWidget {
  final int index;
  const Tile(this.index, {super.key});
  @override
  @pragma('vm:never-inline')
  Widget build(BuildContext context) {
    final w = layoutMetric(index);
    return SizedBox(width: w.toDouble(), child: Text('tile $index w=$w'));
  }
}

class Counter extends StatefulWidget {
  const Counter({super.key});
  @override
  State<Counter> createState() => CounterState();
}

class CounterState extends State<Counter> {
  int _count = 0;
  @pragma('vm:never-inline')
  void increment() {
    setState(() {
      _count += 2;
    });
  }

  @override
  @pragma('vm:never-inline')
  Widget build(BuildContext context) {
    return GestureDetector(onTap: increment, child: Text('count=$_count'));
  }
}

class App extends StatelessWidget {
  const App({super.key});
  @override
  @pragma('vm:never-inline')
  Widget build(BuildContext context) {
    return Column(children: const [Tile(1), Tile(2), Counter()]);
  }
}

void main() => runApp(const App());
