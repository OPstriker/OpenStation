import { Compass, Gauge, Leaf, Wind } from "lucide-react"

import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar"
import { type Item, Main } from "./Main"

// One entry per sensor page. Add a route under src/routes/_layout/ and an
// item here when a new sensor comes online.
const sensorItems: Item[] = [
  { icon: Wind, title: "Wind", path: "/" },
  { icon: Compass, title: "Wind direction", path: "/wind-direction" },
  { icon: Gauge, title: "Barometer", path: "/barometer" },
  { icon: Leaf, title: "Air quality", path: "/air-quality" },
]

export function AppSidebar() {
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-6 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:items-center">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        <Main label="Sensors" items={sensorItems} />
      </SidebarContent>
      <SidebarFooter>
        <SidebarAppearance />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
