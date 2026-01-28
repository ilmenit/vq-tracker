
class EventType:
    STATE_CHANGED = "state_changed"             # Generic state update
    PLAYER_MODE_CHANGED = "player_mode_changed" # Specific mode change
    CONSTRAINT_APPLIED = "constraint_applied"   # A constraint was enforced (log this)
    CONSTRAINT_LIFTED = "constraint_lifted"     # A constraint was removed
    
    FILE_ADDED = "file_added"
    FILE_REMOVED = "file_removed"
    FILE_LIST_CLEARED = "file_list_cleared"
    
    LOG_MESSAGE = "log_message"                 # Request to log something
    BUILD_STARTED = "build_started"
    BUILD_FINISHED = "build_finished"
    HISTORY_UPDATED = "history_updated"

class EventBus:
    def __init__(self):
        self._subscribers = {}

    def subscribe(self, event_type, callback):
        """Subscribe a callback to an event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def publish(self, event_type, data=None):
        """Publish an event to all subscribers."""
        if event_type in self._subscribers:
            for callback in self._subscribers[event_type]:
                try:
                    callback(data)
                except Exception as e:
                    print(f"Error in event handler for {event_type}: {e}")
