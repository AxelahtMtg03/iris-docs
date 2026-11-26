// Rend la zone de titre à la page. Écrit en C# : Windows appelle WndProc en permanence,
// et un gestionnaire en Python pourrait figer la fenêtre en attendant l'interpréteur.
using System;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace Iris
{
    public class Frame : NativeWindow
    {
        [StructLayout(LayoutKind.Sequential)]
        struct Rect { public int Left, Top, Right, Bottom; }

        [DllImport("user32.dll")] static extern bool IsZoomed(IntPtr window);
        [DllImport("user32.dll")] static extern uint GetDpiForWindow(IntPtr window);
        [DllImport("user32.dll")] static extern int GetSystemMetricsForDpi(int index, uint dpi);
        [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr window, out Rect area);
        [DllImport("user32.dll")] static extern bool PostMessage(IntPtr window, int message, IntPtr w, IntPtr l);
        [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr window, IntPtr after, int x, int y, int width, int height, int flags);
        [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr window, int attribute, ref int value, int size);

        const int WM_NCCALCSIZE = 0x83, WM_NCHITTEST = 0x84, WM_SYSCOMMAND = 0x112;
        const int HTCLIENT = 1, HTTOP = 12, HTTOPLEFT = 13, HTTOPRIGHT = 14;

        readonly Form form;
        readonly IntPtr window;
        readonly int grip;  // bande, en pixels logiques, qui redimensionne par le haut

        public Frame(Form form, int grip)
        {
            this.form = form;
            this.grip = grip;
            window = form.Handle;
            AssignHandle(window);
            form.Resize += delegate { Pad(); };
            // même taille et même place, cadre recalculé
            SetWindowPos(window, IntPtr.Zero, 0, 0, 0, 0, 0x1 | 0x2 | 0x4 | 0x20);
            Pad();
        }

        int Scaled(int pixels) { return (int)(pixels * GetDpiForWindow(window) / 96); }

        void Pad()
        {
            form.Padding = new Padding(0, IsZoomed(window) ? 0 : Scaled(grip), 0, 0);
        }

        protected override void WndProc(ref Message m)
        {
            if (m.Msg == WM_NCCALCSIZE && m.WParam != IntPtr.Zero)
            {
                int top = Marshal.ReadInt32(m.LParam, 4);
                base.WndProc(ref m);
                if (IsZoomed(window))  // agrandie, la fenêtre déborde de son cadre
                {
                    uint dpi = GetDpiForWindow(window);
                    top += GetSystemMetricsForDpi(33, dpi) + GetSystemMetricsForDpi(92, dpi);
                }
                Marshal.WriteInt32(m.LParam, 4, top);
                return;
            }
            base.WndProc(ref m);
            if (m.Msg != WM_NCHITTEST || m.Result != (IntPtr)HTCLIENT || IsZoomed(window)) return;
            Rect area;
            GetWindowRect(window, out area);
            long point = m.LParam.ToInt64();
            int x = (short)(point & 0xFFFF), y = (short)((point >> 16) & 0xFFFF);
            if (y >= area.Top + Scaled(grip)) return;
            int corner = Scaled(16);
            m.Result = (IntPtr)(x < area.Left + corner ? HTTOPLEFT
                : x >= area.Right - corner ? HTTOPRIGHT : HTTOP);
        }

        // ---------- Demandes de la page, venues d'un autre fil ----------
        public bool Maximized { get { return IsZoomed(window); } }

        // 0xF020 réduire, 0xF030 agrandir, 0xF120 restaurer, 0xF060 fermer
        public void Command(int command)
        {
            PostMessage(window, WM_SYSCOMMAND, (IntPtr)command, IntPtr.Zero);
        }

        // Accorde la bande du haut et le liseré de la fenêtre au thème (« #rrggbb »).
        public void Paint(string html, bool dark)
        {
            Color color = ColorTranslator.FromHtml(html);
            form.BeginInvoke((MethodInvoker)delegate
            {
                int mode = dark ? 1 : 0, border = ColorTranslator.ToWin32(color);
                DwmSetWindowAttribute(window, 20, ref mode, 4);    // barre en mode sombre
                DwmSetWindowAttribute(window, 34, ref border, 4);  // couleur du liseré
                form.BackColor = color;
            });
        }
    }
}
