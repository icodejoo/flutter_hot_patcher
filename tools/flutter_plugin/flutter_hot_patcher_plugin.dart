import 'package:flutter/services.dart';

class FlutterHotPatcherPlugin {
  static const MethodChannel _channel =
      MethodChannel('flutter_hot_patcher_plugin');

  static Future<int> init(String dataDir, String fingerprint) async {
    return await _channel.invokeMethod<int>('init', {
          'dataDir': dataDir,
          'fingerprint': fingerprint,
        }) ??
        -1;
  }

  static Future<int> stagePatch(String bundleDir, String pubkeyHex) async {
    return await _channel.invokeMethod<int>('stagePatch', {
          'bundleDir': bundleDir,
          'pubkeyHex': pubkeyHex,
        }) ??
        -1;
  }

  static Future<String?> getNextBootPatchDir() async {
    return _channel.invokeMethod<String>('getNextBootPatchDir');
  }

  static Future<void> confirmHealth() async {
    await _channel.invokeMethod('confirmHealth');
  }

  static Future<String> getStateJson() async {
    return await _channel.invokeMethod<String>('getStateJson') ?? '{}';
  }
}
