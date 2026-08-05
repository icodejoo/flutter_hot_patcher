import 'dart:typed_data';
import 'package:flutter/services.dart';

class DartHotpatchPlugin {
  static const MethodChannel _channel = MethodChannel('dart_hotpatch_plugin');

  /// Get engine capabilities (checks if dart_dynamic_modules is enabled)
  static Future<String> getEngineCapabilities() async {
    return await _channel.invokeMethod<String>('getEngineCapabilities') ?? 'Unknown';
  }

  /// Test calling Dart_LoadLibraryFromBytecode with bytecode data.
  /// Returns either "API_CALLABLE:SUCCESS" or "API_CALLABLE:ERROR:..." 
  /// Both mean the API is accessible (the error is expected for invalid bytecode).
  /// Returns "NOT_AVAILABLE:..." if the engine doesn't support dynamic modules.
  static Future<String> testLoadBytecode(Uint8List bytecode) async {
    try {
      final result = await _channel.invokeMethod<String>('testLoadBytecode', {
        'bytecode': bytecode,
      });
      return result ?? 'null result';
    } on PlatformException catch (e) {
      return 'NOT_AVAILABLE:${e.message}';
    }
  }
}
