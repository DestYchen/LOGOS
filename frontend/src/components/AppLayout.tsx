import { Outlet } from "react-router-dom"
import Sidebar from "./Sidebar"

const AppLayout = () => {
  return (
    <div className="app-frame">
      <Sidebar />
      <main className="app-content">
        <Outlet />
      </main>
    </div>
  )
}

export default AppLayout

