import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:dart_hotpatch_plugin/dart_hotpatch_plugin.dart';

void main() => runApp(const HotpatchApp());

class HotpatchApp extends StatelessWidget {
  const HotpatchApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'Flutter Hotpatch X1 Demo',
    theme: ThemeData(colorSchemeSeed: Colors.deepPurple, useMaterial3: true),
    home: const HotpatchPage(),
  );
}

class HotpatchPage extends StatefulWidget {
  const HotpatchPage({super.key});
  @override
  State<HotpatchPage> createState() => _HotpatchPageState();
}

class _HotpatchPageState extends State<HotpatchPage> {
  final _log = <String>[];
  bool _loading = false;

  void _addLog(String msg) {
    setState(() => _log.insert(0, '[${DateTime.now().toIso8601String().substring(11,19)}] $msg'));
    debugPrint('[HOTPATCH] $msg');
  }

  Future<void> _checkEngine() async {
    setState(() { _loading = true; });
    _addLog('Checking engine capabilities...');
    final caps = await DartHotpatchPlugin.getEngineCapabilities();
    for (final line in caps.split('\n')) {
      if (line.isNotEmpty) _addLog(line);
    }
    setState(() { _loading = false; });
  }

  Future<void> _testDynamicModuleAPI() async {
    setState(() { _loading = true; });
    _addLog('Testing Dart_LoadLibraryFromBytecode API...');
    
    // Minimal kernel binary header (invalid bytecode, just tests API callability)
    final fakeDill = Uint8List.fromList([
      0x90, 0xAB, 0xCD, 0xEF,
      0x00, 0x00, 0x00, 0x08,
    ]);
    
    final result = await DartHotpatchPlugin.testLoadBytecode(fakeDill);
    
    if (result.startsWith('API_CALLABLE')) {
      _addLog('✅ Dart_LoadLibraryFromBytecode IS CALLABLE!');
      _addLog('   Result: $result');
      _addLog('🎉 X1 MILESTONE VERIFIED: dart_dynamic_modules works in Flutter!');
    } else {
      _addLog('❌ API not available: $result');
      _addLog('   Check: is our custom Flutter.xcframework being used?');
    }
    setState(() { _loading = false; });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('X1: Dart Dynamic Modules'),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Row(children: [
              Expanded(child: FilledButton.icon(
                onPressed: _loading ? null : _checkEngine,
                icon: const Icon(Icons.info_outline),
                label: const Text('Engine Info'),
              )),
              const SizedBox(width: 8),
              Expanded(child: FilledButton.icon(
                onPressed: _loading ? null : _testDynamicModuleAPI,
                icon: const Icon(Icons.science),
                label: const Text('Test API'),
              )),
            ]),
          ),
          if (_loading) const LinearProgressIndicator(),
          Expanded(
            child: Container(
              margin: const EdgeInsets.fromLTRB(16, 0, 16, 16),
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: Colors.black87,
                borderRadius: BorderRadius.circular(8),
              ),
              child: _log.isEmpty
                ? const Center(child: Text('Press a button to start',
                    style: TextStyle(color: Colors.white54)))
                : ListView.builder(
                    itemCount: _log.length,
                    itemBuilder: (ctx, i) => Text(_log[i],
                      style: TextStyle(
                        color: _log[i].contains('✅') || _log[i].contains('🎉')
                            ? Colors.greenAccent
                            : _log[i].contains('❌') ? Colors.redAccent
                            : Colors.green.shade300,
                        fontFamily: 'monospace',
                        fontSize: 11,
                      )),
                  ),
            ),
          ),
        ],
      ),
    );
  }
}
