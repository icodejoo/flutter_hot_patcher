import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'dart_hotpatch_plugin_platform_interface.dart';

/// An implementation of [DartHotpatchPluginPlatform] that uses method channels.
class MethodChannelDartHotpatchPlugin extends DartHotpatchPluginPlatform {
  /// The method channel used to interact with the native platform.
  @visibleForTesting
  final methodChannel = const MethodChannel('dart_hotpatch_plugin');

  @override
  Future<String?> getPlatformVersion() async {
    final version = await methodChannel.invokeMethod<String>('getPlatformVersion');
    return version;
  }
}
