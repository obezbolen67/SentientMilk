// NAME.exe, the program an app folder starts from; scripts/bundle.py fills in the @...@ values and compiles
// it with the C# compiler Windows has. It runs the folder's Python in this process, so Windows shows the
// app's own name, icon and version where python(w).exe would show "Python", and the one new program to
// sign is this one. The runtime's python3XY._pth, beside its DLL, sets the paths as for python.exe.
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;

[assembly: AssemblyTitle(Host.Name)]
[assembly: AssemblyProduct(Host.Name)]
[assembly: AssemblyCompany(@PUBLISHER@)]
[assembly: AssemblyVersion(@VERSION@)]
[assembly: AssemblyFileVersion(@VERSION@)]

public static class Host
{
    public const string Name = @NAME@;
    const string Module = @MODULE@;

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    delegate int PyMain(int argc, [MarshalAs(UnmanagedType.LPArray, ArraySubType = UnmanagedType.LPWStr)] string[] argv);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern IntPtr LoadLibraryExW(string path, IntPtr reserved, uint flags);

    [DllImport("kernel32.dll", CharSet = CharSet.Ansi, ExactSpelling = true)]
    static extern IntPtr GetProcAddress(IntPtr module, string name);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern int MessageBoxW(IntPtr owner, string text, string caption, uint type);

    [STAThread]  // a single-threaded apartment, as with python(w).exe: what Qt and UI Automation expect
    public static int Main(string[] args)
    {
        string runtime = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "runtime");
        return Run(runtime, Module, Environment.GetCommandLineArgs()[0], args);
    }

    // python -m MODULE ARGS, on the Python in runtime. A restart that names the module itself
    // (PROGRAM -m MODULE ARGS) runs it once.
    public static int Run(string runtime, string module, string program, string[] args)
    {
        IntPtr python = IntPtr.Zero;
        string[] dlls = Directory.Exists(runtime) ? Directory.GetFiles(runtime, "python3*.dll") : new string[0];
        foreach (string dll in dlls)
        {
            if (Path.GetFileName(dll).Length > "python3.dll".Length)  // python3XY.dll, not the stable-ABI one
            {
                python = LoadLibraryExW(dll, IntPtr.Zero, 0x8);  // LOAD_WITH_ALTERED_SEARCH_PATH: its own DLLs
            }
        }
        IntPtr entry = python == IntPtr.Zero ? IntPtr.Zero : GetProcAddress(python, "Py_Main");
        if (entry == IntPtr.Zero)
        {
            MessageBoxW(IntPtr.Zero, Name + " cannot start: its runtime folder is missing or damaged. Reinstall " +
                        Name + ".", Name, 0x10);
            return 1;
        }
        PyMain main = (PyMain)Marshal.GetDelegateForFunctionPointer(entry, typeof(PyMain));
        List<string> argv = new List<string> { program, "-m", module };
        int skip = args.Length >= 2 && args[0] == "-m" && args[1] == module ? 2 : 0;
        for (int i = skip; i < args.Length; i++)
        {
            argv.Add(args[i]);
        }
        return main(argv.Count, argv.ToArray());
    }
}
