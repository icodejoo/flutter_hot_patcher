import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';

void main() {
  runApp(const HotPatchTestApp());
}

class HotPatchTestApp extends StatelessWidget {
  const HotPatchTestApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'HotPatch Flutter Test',
      theme: ThemeData(colorSchemeSeed: Colors.blue),
      home: const HotPatchScreen(),
    );
  }
}

class HotPatchScreen extends StatefulWidget {
  const HotPatchScreen({super.key});

  @override
  State<HotPatchScreen> createState() => _HotPatchScreenState();
}

class _HotPatchScreenState extends State<HotPatchScreen> {
  static const _channel = MethodChannel('flutter_hot_patcher_plugin');

  String _status = 'Initializing...';
  String _patchResult = 'Pending';
  String _stateJson = '{}';
  bool _loading = true;

  // Constant for the patch public key (from keygen.py)
  static const _pubkeyHex =
      '9d2550fb40571238ee6bd8459ffa60bb2c121249abf44bebe0c1218faec9e82f';
  static const _buildFingerprint = '1.0+flutter';

  @override
  void initState() {
    super.initState();
    _runHotPatch();
  }

  Future<void> _runHotPatch() async {
    try {
      // App data directory for Updater state
      final supportDir = await getApplicationSupportDirectory();
      final dataDir = '${supportDir.path}/hotpatch_updater';
      await Directory(dataDir).create(recursive: true);

      // Step 1: Init Updater (runs boot-loop watchdog)
      final initResult = await _channel.invokeMethod<int>('init', {
        'dataDir': dataDir,
        'fingerprint': _buildFingerprint,
      });

      // Step 2: Stage patch bundle from app bundle (if not already staged)
      var patchDir = await _channel.invokeMethod<String?>('getNextBootPatchDir');

      if (patchDir == null) {
        // Look for patch_bundle in app bundle
        final bundlePath =
            '${Directory.current.path}/patch_bundle'; // approximate
        final stageResult = await _channel.invokeMethod<int>('stagePatch', {
          'bundleDir': bundlePath,
          'pubkeyHex': _pubkeyHex,
        });

        patchDir = await _channel.invokeMethod<String?>('getNextBootPatchDir');
      }

      // Step 3: Load bytecode and get result
      // NOTE: Dart_LoadLibraryFromBytecode requires custom Flutter Engine
      // With standard Engine: this returns "UPDATER_READY"
      // With custom Engine: loads patch.dill and returns patched function result
      String result;
      if (patchDir != null) {
        final dillPath = '$patchDir/bytecode/patch.dill';
        if (await File(dillPath).exists()) {
          // Custom Engine path: load bytecode directly
          // result = await _loadBytecodeAndInvoke(dillPath);
          result = 'PATCH_BUNDLE_FOUND: $patchDir\n(bytecode invoke needs custom engine)';
        } else {
          result = 'PATCH_DIR_SET: $patchDir\n(no patch.dill yet)';
        }
      } else {
        result = 'BASELINE (no patch staged)';
      }

      // Step 4: Confirm health
      await _channel.invokeMethod('confirmHealth');

      // Get state JSON for display
      final stateJson = await _channel.invokeMethod<String>('getStateJson') ?? '{}';

      setState(() {
        _status = 'init=$initResult ✓ health confirmed';
        _patchResult = result;
        _stateJson = stateJson;
        _loading = false;
      });
    } catch (e, st) {
      setState(() {
        _status = 'Error: $e';
        _patchResult = 'FAILED';
        _loading = false;
      });
      debugPrint('HotPatch error: $e\n$st');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('HotPatch Flutter Test'),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _card('Status', _status, Colors.blue),
                  const SizedBox(height: 12),
                  _card('Patch Result', _patchResult,
                      _patchResult.contains('PATCHED')
                          ? Colors.green
                          : Colors.orange),
                  const SizedBox(height: 12),
                  _card('Updater State (JSON)', _stateJson, Colors.grey),
                  const Spacer(),
                  ElevatedButton.icon(
                    onPressed: _runHotPatch,
                    icon: const Icon(Icons.refresh),
                    label: const Text('Reload'),
                  ),
                ],
              ),
            ),
    );
  }

  Widget _card(String title, String content, Color color) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title,
                style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                    color: color)),
            const SizedBox(height: 4),
            Text(content,
                style: const TextStyle(fontSize: 14, fontFamily: 'monospace')),
          ],
        ),
      ),
    );
  }
}
