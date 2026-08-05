import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'flutter_hot_patcher_plugin_platform_interface.dart';

/// An implementation of [FlutterHotPatcherPluginPlatform] that uses method channels.
class MethodChannelFlutterHotPatcherPlugin extends FlutterHotPatcherPluginPlatform {
  /// The method channel used to interact with the native platform.
  @visibleForTesting
  final methodChannel = const MethodChannel('flutter_hot_patcher_plugin');

  @override
  Future<String?> getPlatformVersion() async {
    final version = await methodChannel.invokeMethod<String>('getPlatformVersion');
    return version;
  }
}
