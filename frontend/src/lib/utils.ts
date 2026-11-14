/**
 * @fileoverview 跨组件复用的通用工具函数。
 */
import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** 合并类名：后写的工具类覆盖先写的同族工具类。 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
