import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { LayoutDashboard, Video, Map, Settings, PlaySquare, FileText, BarChart3, Activity, Database, BrainCircuit } from "lucide-react";

const NAV_ITEMS = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard },
  { name: "Monitor", href: "/monitor", icon: Video },
  { name: "Dataset", href: "/dataset", icon: Database },
  { name: "Training", href: "/training", icon: BrainCircuit },
  { name: "Map", href: "/map", icon: Map },
  { name: "Control", href: "/control", icon: PlaySquare },
  { name: "Nodes", href: "/nodes", icon: Activity },
  { name: "Patrol", href: "/patrol", icon: Map },
  { name: "Analytics", href: "/analytics", icon: BarChart3 },
  { name: "Logs", href: "/logs", icon: FileText },
  { name: "Settings", href: "/settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <div className="w-64 bg-slate-900 text-slate-300 flex flex-col h-full border-r border-slate-800">
      <div className="h-16 flex items-center px-6 border-b border-slate-800">
        <span className="text-xl font-bold text-white tracking-wide">ROBOT<span className="text-blue-500">OS</span></span>
      </div>
      <nav className="flex-1 py-4 overflow-y-auto">
        <ul className="space-y-1 px-3">
          {NAV_ITEMS.map((item) => {
            const isActive = pathname === item.href;
            const Icon = item.icon;
            return (
              <li key={item.name}>
                <Link
                  href={item.href}
                  className={cn(
                    "flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors text-sm font-medium",
                    isActive 
                      ? "bg-blue-600/10 text-blue-400" 
                      : "hover:bg-slate-800 hover:text-white"
                  )}
                >
                  <Icon className="w-5 h-5" />
                  {item.name}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </div>
  );
}
