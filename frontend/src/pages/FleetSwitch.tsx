/**
 * @fileoverview 换船页外壳：info/rotation/training/equipment 四个页签共用一个路由，选中项写在 URL ?tab 里。
 */

import {useParams, useSearchParams} from 'react-router-dom'
import {useApp} from '../app/context'
import {PageTitle} from '../components/ui'
import {Tabs, TabsContent, TabsList, TabsTrigger} from '../components/ui/tabs'
import {FleetInfoPage} from './FleetInfoPage'
import {FleetRotation} from './FleetRotation'
import {FleetTraining} from './FleetTraining'
import {FleetEquipment} from './FleetEquipment'

/** 只整合页面入口；各页签继续使用原有的配置和游戏操作。 */
export function FleetSwitch() {
  const {instance = ''} = useParams(), {ui, t} = useApp(), [params, setParams] = useSearchParams()
  const value = params.get('tab')
  const tab = value === 'rotation' || value === 'training' || value === 'equipment' ? value : 'info'
  const tabs = [
    {id: 'info', label: t('Task.FleetInfo.name'), content: <FleetInfoPage/>},
    {id: 'rotation', label: ui('rotation.title'), content: <FleetRotation/>},
    {id: 'training', label: ui('training.title'), content: <FleetTraining/>},
    {id: 'equipment', label: ui('fleetEquipment.title'), content: <FleetEquipment/>},
  ]
  const active = tabs.find(item => item.id === tab)!
  return <div className="fleet-switch">
    <PageTitle title={ui('rotation.pageTitle')}/>
    <Tabs value={tab} onValueChange={next => setParams({tab: next}, {replace: true})} className="gap-4">
      <TabsList aria-label={ui('rotation.pageTitle')}>
        {tabs.map(({id, label}) => <TabsTrigger key={id} value={id} id={`fleet-switch-tab-${id}`}>{label}</TabsTrigger>)}
      </TabsList>
      {/* key 带上实例名：切换实例时强制重挂载页签内容，避免上一个实例的状态残留 */}
      <TabsContent key={`${instance}:${tab}`} value={tab} id={`fleet-switch-${tab}`} aria-labelledby={`fleet-switch-tab-${tab}`}>
        {active.content}
      </TabsContent>
    </Tabs>
  </div>
}
