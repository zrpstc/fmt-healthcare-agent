"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Bot, Database, FileText, FlaskConical, LogIn, MessageSquare, PanelLeftClose, PanelLeftOpen, Settings2, UserCircle, UserPlus } from "lucide-react";
import { api, AuthUser } from "@/lib/api";
import { AuthAccess } from "@/components/auth-access";

const navigation = [
  { href: "/chat", label: "智能体对话", icon: MessageSquare },
  { href: "/samples", label: "样本与分析", icon: FlaskConical },
  { href: "/knowledge", label: "证据知识库", icon: Database },
  { href: "/reports", label: "报告中心", icon: FileText },
  { href: "/settings", label: "Agent 与 Skills", icon: Settings2 },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [user,setUser]=useState<AuthUser|null>(null);
  const [authOpen,setAuthOpen]=useState<"login"|"register"|null>(null);
  const [sidebarCollapsed,setSidebarCollapsed]=useState(false);
  useEffect(()=>{const refresh=()=>{if(!window.localStorage.getItem("wgs-auth-token")){setUser(null);return}api.me().then(setUser).catch(()=>{window.localStorage.removeItem("wgs-auth-token");setUser(null)})};refresh();window.addEventListener("wgs-auth-changed",refresh);return()=>window.removeEventListener("wgs-auth-changed",refresh)},[]);
  useEffect(()=>{const requested=new URLSearchParams(window.location.search).get("auth");if(requested==="login"||requested==="register")setAuthOpen(requested)},[pathname]);
  useEffect(()=>{setSidebarCollapsed(window.localStorage.getItem("wgs-sidebar-collapsed")==="1")},[]);
  const toggleSidebar=()=>setSidebarCollapsed(value=>{const next=!value;window.localStorage.setItem("wgs-sidebar-collapsed",next?"1":"0");return next});
  if(pathname==="/"||pathname.startsWith("/r/")||pathname.startsWith("/share/"))return <>{children}</>;
  return (
    <div className={`app-frame ${sidebarCollapsed?"sidebar-is-collapsed":""}`}>
      <aside className="global-sidebar" aria-label="工作空间导航">
        <div className="brand-lockup">
          <div className="brand-mark"><Bot size={20} /></div>
          <div className="brand-copy"><strong>WGS·FMT</strong><span>Research workspace</span></div>
          <button className="sidebar-toggle" onClick={toggleSidebar} title={sidebarCollapsed?"展开工作空间":"收起工作空间"} aria-label={sidebarCollapsed?"展开工作空间":"收起工作空间"}>{sidebarCollapsed?<PanelLeftOpen size={17}/>:<PanelLeftClose size={17}/>}</button>
        </div>
        <nav className="main-nav">
          <p className="nav-label">工作空间</p>
          {navigation.map(({ href, label, icon: Icon }) => (
            <Link className={`nav-item ${pathname === href || pathname.startsWith(`${href}/`) ? "is-active" : ""}`} href={href} key={href}>
              <Icon size={18}/><span>{label}</span>
            </Link>
          ))}
        </nav>
        <div className="sidebar-status">
          <span className="status-pulse"/><div><strong>受控智能体</strong><small>工具调用全程留痕</small></div>
        </div>
      </aside>
      <main className="workspace-main">
        <header className="topbar">
          <div><span className="crumb">宏基因组科研平台</span></div>
          <div className="topbar-account"><div className="topbar-badge"><span/>仅供科研与教育使用</div>{user?<Link className="account-chip" href="/settings"><UserCircle size={17}/><span><strong>{user.display_name||user.username}</strong><small>{user.role==="admin"?"管理员":user.role==="viewer"?"只读用户":"普通用户"}</small></span></Link>:<><button className="button button-ghost" onClick={()=>setAuthOpen("login")}><LogIn size={14}/>登录</button><button className="button button-primary" onClick={()=>setAuthOpen("register")}><UserPlus size={14}/>注册</button></>}</div>
        </header>
        <div className="workspace-content">{children}</div>
      </main>
      {authOpen&&<AuthAccess key={authOpen} modal initialMode={authOpen} onClose={()=>setAuthOpen(null)} onSuccess={result=>{setUser(result.user);setAuthOpen(null)}}/>}
    </div>
  );
}
