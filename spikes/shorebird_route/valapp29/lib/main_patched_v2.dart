import 'package:flutter/material.dart';

/// 被 OTA 补丁替换的函数。
@pragma('vm:never-inline')
String buildLabel() => 'OTA_PATCHED_V2';

void main() => runApp(const ValApp());

class ValApp extends StatelessWidget {
  const ValApp({super.key});

  @override
  Widget build(BuildContext context) {
    final label = buildLabel();
    final patched = label != 'BASELINE_V1';
    return MaterialApp(
      home: Scaffold(
        backgroundColor: patched ? Colors.green.shade50 : Colors.orange.shade50,
        body: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(label,
                  style: TextStyle(
                      fontSize: 30,
                      fontWeight: FontWeight.bold,
                      color: patched ? Colors.green.shade900 : Colors.orange.shade900)),
              const SizedBox(height: 12),
              Text(patched ? 'PATCH ACTIVE' : 'baseline',
                  style: const TextStyle(fontSize: 16)),
            ],
          ),
        ),
      ),
    );
  }
}
