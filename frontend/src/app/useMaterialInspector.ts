/**
 * @fileoverview 检视器与全真预览共用的状态钩子：家族自定义参数，以及当前区域与两个样本层的联动。
 */

import { useEffect, useState } from 'react'
import { applyCustomLayer, type Family } from './theme'
import { readFamilyCustom, type FamilyCustom } from './themeCustom'
import type { RegionId } from './themeKnobs'

/**
 * 读取并刷新主题家族自定义参数。
 *
 * @param family 主题家族。
 * @returns 当前自定义参数与应用最新设置的函数。
 */
export function useFamilyCustom(family: Family) {
  const [custom, setCustom] = useState<FamilyCustom>(() => readFamilyCustom(family))
  useEffect(() => setCustom(readFamilyCustom(family)), [family])
  const refresh = () => {
    applyCustomLayer()
    setCustom(readFamilyCustom(family))
  }
  return {custom, refresh}
}

/**
 * 管理材质检视器当前区域与样本层显隐。
 *
 * @param initial 初始调节区域。
 * @returns 区域、样本显隐状态及其更新函数。
 */
export function useSampleLayers(initial: RegionId = 'surface') {
  const [region, setRegion] = useState<RegionId>(initial)
  const [showModal, setShowModal] = useState(false)
  const [showMenu, setShowMenu] = useState(false)
  const select = (next: RegionId) => {
    setRegion(next)
    setShowModal(next === 'modal')
    setShowMenu(next === 'menu')
  }
  return {region, showModal, showMenu, select, setShowModal, setShowMenu}
}
