import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';

import 'package:dart_internal/dart_internal.dart' as loader;
import 'package:route_a_flutter/hot.dart' as hot;
import 'package:route_a_flutter/patchable.dart' as patchable;

/// Everything is reported through the engine log channel so a run can be judged
/// from `idevicesyslog` without touching the screen.
void report(String line) => debugPrint('FHP_A=$line');

/// Runs [hot.hotLoop] until the time budget is spent and reports ns/call.
/// A fixed repetition count cannot work here: the three configurations differ
/// by three orders of magnitude, so the budget adapts instead.
void bench(String mode, {int budgetMs = 400, int warmupMs = 100}) {
  var sink = 0;
  final warm = Stopwatch()..start();
  while (warm.elapsedMilliseconds < warmupMs) {
    sink += hot.hotLoop();
  }
  warm.stop();

  var calls = 0;
  final sw = Stopwatch()..start();
  while (sw.elapsedMicroseconds < budgetMs * 1000) {
    sink += hot.hotLoop();
    calls++;
  }
  sw.stop();

  final nsPerCall = sw.elapsedMicroseconds * 1000 / calls;
  final nsPerIter = nsPerCall / 10000;
  report('BENCH mode=$mode calls=$calls elapsed_us=${sw.elapsedMicroseconds} '
      'ns_per_call=${nsPerCall.toStringAsFixed(1)} '
      'ns_per_iter=${nsPerIter.toStringAsFixed(3)} sink=${sink & 0xffff}');
}

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  report('before=${patchable.label()}');

  var mode = 'native';
  var status = 'skipped';
  try {
    final dir = await getApplicationDocumentsDirectory();
    final modeFile = File('${dir.path}/mode.txt');
    if (modeFile.existsSync()) mode = modeFile.readAsStringSync().trim();

    if (mode == 'kbc') {
      final f = File('${dir.path}/module.bytecode');
      if (!f.existsSync()) {
        status = 'no-module';
      } else {
        final Uint8List bytes = f.readAsBytesSync();
        report('module=${bytes.length}B');
        await loader.loadModuleFromBytes(bytes);
        status = 'loaded';
      }
    }
  } catch (e) {
    status = 'error: $e';
  }
  report('mode=$mode status=$status');
  report('after=${patchable.label()}');

  bench(mode);

  runApp(MyApp(mode: mode, status: status));
}

class MyApp extends StatelessWidget {
  const MyApp({super.key, required this.mode, required this.status});
  final String mode;
  final String status;
  @override
  Widget build(BuildContext context) => MaterialApp(
        home: Scaffold(
          body: Center(
            child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
              Text(patchable.label(),
                  style: const TextStyle(fontSize: 28, fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              Text('$mode / $status'),
            ]),
          ),
        ),
      );
}
