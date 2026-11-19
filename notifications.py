"""Store brief notifications in the transaction that records the workflow event."""

EVENTS = {
    "submitted": ("New brief submitted", "A new project brief is ready for your review.", "brief", "service_provider"),
    "revision_requested": ("Revision requested", "Your designer has requested changes to your brief.", "revision", "client"),
    "resubmitted": ("Revised brief submitted", "A revised project brief is ready for review.", "revision", "service_provider"),
    "approved": ("Brief approved", "Your project brief has been approved for design.", "check", "client"),
}


def record_notification(db, brief_id, event, event_reference):
    title, message, _, role = EVENTS[event]
    db.execute(
        """
        INSERT INTO notifications (
            recipient_id, recipient_role, brief_id, event_type, title, message, event_reference
        )
        SELECT CASE WHEN ? = 'client' THEN client_id ELSE assigned_provider_id END,
               ?, id, ?, ?, ?, ?
        FROM project_briefs WHERE id = ?
        ON CONFLICT (brief_id, event_type, event_reference) DO NOTHING
        """,
        (role, role, event, title, message, event_reference, brief_id),
    )


# Check the current brief assignment as well as the original recipient.
VISIBLE_NOTIFICATIONS = """
    FROM notifications n
    JOIN project_briefs b ON b.id = n.brief_id
    WHERE n.recipient_id = ? AND n.recipient_role = ?
      AND (
        (n.recipient_role = 'client' AND b.client_id = n.recipient_id)
        OR (n.recipient_role = 'service_provider' AND b.assigned_provider_id = n.recipient_id
            AND b.status != 'draft')
      )
"""
