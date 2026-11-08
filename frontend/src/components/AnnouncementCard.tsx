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
