// Écrit sur un raccourci l'identifiant d'application, que WScript ne sait pas poser.
// La barre des tâches s'en sert pour épingler Iris avec son icône, et non celle de Python.
using System;
using System.Runtime.InteropServices;
public static class IrisShortcut {
  [StructLayout(LayoutKind.Sequential, Pack = 4)] struct Key { public Guid Id; public int Index; }
  [StructLayout(LayoutKind.Sequential)] struct Value { public ushort Type, A, B, C; public IntPtr Text, Unused; }
  [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface Store {
    void GetCount(out int count);
    void GetAt(int index, out Key key);
    void GetValue(ref Key key, out Value value);
    void SetValue(ref Key key, ref Value value);
    void Commit();
  }
  [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
  static extern void SHGetPropertyStoreFromParsingName(
    string path, IntPtr context, int flags, ref Guid id, out Store store);
  public static void SetAppId(string path, string appId) {
    Guid id = typeof(Store).GUID;
    Store store;
    SHGetPropertyStoreFromParsingName(path, IntPtr.Zero, 2, ref id, out store);
    Key key = new Key { Id = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), Index = 5 };
    Value value = new Value { Type = 31, Text = Marshal.StringToCoTaskMemUni(appId) };
    try { store.SetValue(ref key, ref value); store.Commit(); }
    finally { Marshal.FreeCoTaskMem(value.Text); Marshal.ReleaseComObject(store); }
  }
}
