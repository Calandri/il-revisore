"""Task registry for task lookup."""


from .base import BaseTask
from .develop import DevelopTask
from .review import ReviewTask


class TaskRegistry:
    """Registry for task types."""

    def __init__(self):
        """Initialize registry with built-in tasks."""
        self._tasks: dict[str, type[BaseTask]] = {}

        # Register built-in tasks
        self.register(ReviewTask)
        self.register(DevelopTask)

    def register(self, task_class: type[BaseTask]) -> None:
        """Register a task type.

        Args:
            task_class: Task class to register.
        """
        # Instantiate to get name
        instance = task_class()
        self._tasks[instance.name] = task_class

    def get(self, name: str) -> type[BaseTask] | None:
        """Get task class by name.

        Args:
            name: Task name.

        Returns:
            Task class or None.
        """
        return self._tasks.get(name)

    def create(self, name: str) -> BaseTask | None:
        """Create task instance by name.

        Args:
            name: Task name.

        Returns:
            Task instance or None.
        """
        task_class = self.get(name)
        if task_class:
            return task_class()
        return None

    def list_tasks(self) -> list[dict]:
        """List all registered tasks.

        Returns:
            List of task info dictionaries.
        """
        result = []
        for _name, task_class in self._tasks.items():
            instance = task_class()
            result.append({
                "name": instance.name,
                "description": instance.description,
            })
        return result

    @property
    def available_tasks(self) -> list[str]:
        """Get list of available task names."""
        return list(self._tasks.keys())


# Global registry instance
_registry: TaskRegistry | None = None


def get_task_registry() -> TaskRegistry:
    """Get global task registry instance."""
    global _registry
    if _registry is None:
        _registry = TaskRegistry()
    return _registry
