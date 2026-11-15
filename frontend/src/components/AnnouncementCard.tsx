/**
 * @fileoverview 系统公告卡片组件。
 */

import { Link } from 'react-router-dom'
import { Megaphone, ExternalLink, Check, ArrowRight } from 'lucide-react'
import type { Announcement } from '../api/types'
import { useApp } from '../app/context'
import { LazyMarkdown } from './LazyMarkdown'

interface AnnouncementCardProps {
  announcement: Announcement
  unread?: boolean
  onMarkRead?: () => void
  showFullLink?: boolean
}

/**
 * 系统公告卡片：未读时加高亮与「新」角标；正文按 Markdown 渲染，url 渲染为外部链接。
 *
 * @param unread 未读态，显示「新」角标与「标为已读」按钮。
 * @param onMarkRead 点击「标为已读」的回调，不传则不显示该按钮。
 * @param showFullLink 是否显示「查看详情」链接；公告全页（/announcement）里以 false 嵌入，避免链接指向当前页。
 */
export function AnnouncementCard({
  announcement,
  unread = false,
  onMarkRead,
  showFullLink = true,
}: AnnouncementCardProps) {
  const { ui } = useApp()

  return (
    <article
      className={`announcement-card panel ${unread ? 'is-unread' : ''}`}
      aria-label={ui('announcement.title')}
    >
      <header className="announcement-header">
        <div className="announcement-badge-group">
          <span className="announcement-icon-badge" aria-hidden="true">
            <Megaphone size={18} />
          </span>
          <span className="announcement-category">{ui('announcement.latest')}</span>
          {unread && <span className="announcement-new-tag">{ui('nav.newBadge')}</span>}
        </div>
        <div className="announcement-header-actions">
          {unread && onMarkRead && (
            <button
              type="button"
              className="button ghost small announcement-read-btn"
              onClick={onMarkRead}
              title={ui('announcement.markAsRead')}
            >
              <Check size={14} />
              <span>{ui('announcement.read')}</span>
            </button>
          )}
          {showFullLink && (
            <Link
              to="/announcement"
              className="announcement-view-more"
              title={ui('announcement.viewAll')}
            >
              <span>{ui('announcement.viewAll')}</span>
              <ArrowRight size={14} />
            </Link>
          )}
        </div>
      </header>

      <h3 className="announcement-title">{announcement.title}</h3>

      {announcement.content && (
        <div className="announcement-body">
          <LazyMarkdown content={announcement.content} />
        </div>
      )}

      {announcement.url && (
        <footer className="announcement-footer">
          <a
            href={announcement.url}
            target="_blank"
            rel="noreferrer"
            className="button secondary small announcement-external-btn"
          >
            <span>{ui('announcement.openExternal')}</span>
            <ExternalLink size={14} />
          </a>
        </footer>
      )}
    </article>
  )
}
