import 'package:plugin_platform_interface/plugin_platform_interface.dart';

import 'dart_hotpatch_plugin_method_channel.dart';

abstract class DartHotpatchPluginPlatform extends PlatformInterface {
  /// Constructs a DartHotpatchPluginPlatform.
  DartHotpatchPluginPlatform() : super(token: _token);

  static final Object _token = Object();

  static DartHotpatchPluginPlatform _instance = MethodChannelDartHotpatchPlugin();

  /// The default instance of [DartHotpatchPluginPlatform] to use.
  ///
  /// Defaults to [MethodChannelDartHotpatchPlugin].
  static DartHotpatchPluginPlatform get instance => _instance;

  /// Platform-specific implementations should set this with their own
  /// platform-specific class that extends [DartHotpatchPluginPlatform] when
  /// they register themselves.
  static set instance(DartHotpatchPluginPlatform instance) {
    PlatformInterface.verifyToken(instance, _token);
    _instance = instance;
  }

  Future<String?> getPlatformVersion() {
    throw UnimplementedError('platformVersion() has not been implemented.');
  }
}
