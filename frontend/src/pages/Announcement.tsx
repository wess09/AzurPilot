/**
 * @fileoverview 系统公告详情展示页面。
 */

import { useEffect } from 'react'
import { Megaphone, RefreshCw } from 'lucide-react'
import { useAnnouncement } from '../app/announcement'
import { useApp } from '../app/context'
import { AnnouncementCard } from '../components/AnnouncementCard'
import { Empty, ErrorBox, Loading, PageTitle } from '../components/ui'

/**
 * 公告详情页：展示当前系统公告并提供刷新；进入页面即把未读标记为已读。
 * 内容列限宽居中（.announcement-page），超宽屏下正文行宽可控、两侧留出壁纸；
 * 刷新按钮走实底次级样式，直接悬在壁纸上也能看清。
 */
export function Announcement() {
  const { ui } = useApp()
  const { data, loading, error, unread, refresh, markAsRead } = useAnnouncement()

  useEffect(() => {
    if (unread && data?.announcementId) {
      markAsRead()
    }
  }, [unread, data, markAsRead])

  return (
    <div className="announcement-page">
      <PageTitle
        title={ui('nav.announcement')}
        actions={
          <button
            type="button"
            className="button secondary"
            disabled={loading}
            onClick={() => void refresh(true)}
          >
            <RefreshCw size={16} className={loading ? 'spin' : ''} />
            <span>{loading ? ui('announcement.refreshing') : ui('announcement.refresh')}</span>
          </button>
        }
      />

      {error && <ErrorBox message={error} />}

      {loading && !data ? (
        <Loading />
      ) : data && (data.title || data.content) ? (
        <AnnouncementCard
          announcement={data}
          unread={unread}
          onMarkRead={markAsRead}
          showFullLink={false}
        />
      ) : (
        <Empty
          icon={<Megaphone size={32} />}
          title={ui('announcement.noAnnouncement')}
        >
          <p>{ui('announcement.noAnnouncementDesc')}</p>
        </Empty>
      )}
    </div>
  )
}
