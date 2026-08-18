import Flutter
import UIKit
import Darwin

// vm_remap probe (C1/C2 foundation check on real iOS hardware).
//
// SimBridge hands out trampolines by duplicating an executable template with
// vm_remap(copy: true, R|X). That primitive is upstream (VirtualMemory::
// DuplicateRX) and the host tests pass, but the host is macOS. The question
// this probe answers is the one only the device can answer: does iOS, under
// code signing, actually permit remapping executable pages and executing the
// copy?
//
// The trampoline arithmetic is pure software and already covered by the host
// unit tests, so this deliberately tests only the OS-controlled part.

@_cdecl("fhp_probe_target")
func fhpProbeTarget(_ x: Int32) -> Int32 {
  return x &* 2 &+ 1
}

private func runVmRemapProbe() -> String {
  let pageSize = UInt(vm_page_size)
  let target: @convention(c) (Int32) -> Int32 = fhpProbeTarget
  let fn = unsafeBitCast(target, to: UInt.self)
  let pageStart = fn & ~(pageSize - 1)
  let offsetInPage = fn - pageStart
  let task = mach_task_self_

  // Reserve a destination the way SimBridge does: plain RW first.
  var dst: vm_address_t = 0
  var kr = vm_allocate(task, &dst, vm_size_t(pageSize), VM_FLAGS_ANYWHERE)
  guard kr == KERN_SUCCESS else {
    return "FHP_PROBE=FAIL stage=vm_allocate kr=\(kr)"
  }

  // The load-bearing call: copy=true, R|X, overwriting the reservation --
  // exactly what DuplicateRX issues.
  var cur = vm_prot_t(VM_PROT_READ | VM_PROT_EXECUTE)
  var max = vm_prot_t(VM_PROT_READ | VM_PROT_EXECUTE)
  kr = vm_remap(task, &dst, vm_size_t(pageSize), 0,
                VM_FLAGS_FIXED | VM_FLAGS_OVERWRITE,
                task, vm_address_t(pageStart), 1,
                &cur, &max, VM_INHERIT_NONE)
  guard kr == KERN_SUCCESS else {
    return "FHP_PROBE=FAIL stage=vm_remap kr=\(kr)"
  }
  guard (cur & vm_prot_t(VM_PROT_EXECUTE)) != 0 else {
    return "FHP_PROBE=FAIL stage=prot cur=\(cur) max=\(max)"
  }

  // Execute the duplicate. If iOS refuses, we find out here rather than after
  // building an engine on top of the assumption.
  typealias Fn = @convention(c) (Int32) -> Int32
  let copied = unsafeBitCast(dst + vm_address_t(offsetInPage), to: Fn.self)
  let got = copied(20)
  let want: Int32 = 41
  if got != want {
    return "FHP_PROBE=FAIL stage=call got=\(got) want=\(want)"
  }

  return "FHP_PROBE=PASS remap_ok exec_ok got=\(got) page=\(pageSize) "
       + "src=0x\(String(pageStart, radix: 16)) dst=0x\(String(dst, radix: 16)) "
       + "cur=\(cur) max=\(max)"
}

@main
@objc class AppDelegate: FlutterAppDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    let _probe = runVmRemapProbe()
    print(_probe)
    FileHandle.standardError.write(_probe.data(using: .utf8)!)
    NSLog("%{public}@", _probe)
    GeneratedPluginRegistrant.register(with: self)
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }
}
