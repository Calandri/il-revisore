"""
Functional tests for TaskQueue management.

Run with: uv run pytest tests/core/test_task_queue_functional.py -v

These tests verify:
1. Priority-based ordering
2. Zombie detection and cleanup
3. Task lifecycle (enqueue → dequeue → complete/fail)
4. Concurrent access safety
5. Requeue behavior
"""

import threading
import time
from datetime import datetime, timedelta

import pytest

from turbowrap.core.task_queue import QueuedTask, TaskQueue, get_task_queue

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def task_queue():
    """Create a fresh task queue for each test."""
    return TaskQueue(max_size=100)


@pytest.fixture
def sample_tasks():
    """Create sample tasks with different priorities."""
    return [
        QueuedTask(
            task_id="task-low",
            task_type="review",
            repository_id="repo-1",
            priority=1,
        ),
        QueuedTask(
            task_id="task-medium",
            task_type="review",
            repository_id="repo-2",
            priority=5,
        ),
        QueuedTask(
            task_id="task-high",
            task_type="fix",
            repository_id="repo-3",
            priority=10,
        ),
    ]


# =============================================================================
# Priority Ordering
# =============================================================================


@pytest.mark.functional
class TestPriorityOrdering:
    """Tests for priority-based task ordering."""

    def test_higher_priority_dequeued_first(self, task_queue, sample_tasks):
        """Higher priority tasks are dequeued before lower priority."""
        # Enqueue in random order
        task_queue.enqueue(sample_tasks[0])  # priority=1
        task_queue.enqueue(sample_tasks[2])  # priority=10
        task_queue.enqueue(sample_tasks[1])  # priority=5

        # Should dequeue in priority order (highest first)
        task1 = task_queue.dequeue()
        task2 = task_queue.dequeue()
        task3 = task_queue.dequeue()

        assert task1.task_id == "task-high"
        assert task1.priority == 10
        assert task2.task_id == "task-medium"
        assert task2.priority == 5
        assert task3.task_id == "task-low"
        assert task3.priority == 1

    def test_same_priority_fifo(self, task_queue):
        """Tasks with same priority are FIFO."""
        task1 = QueuedTask(task_id="task-1", task_type="review", repository_id="repo", priority=5)
        task2 = QueuedTask(task_id="task-2", task_type="review", repository_id="repo", priority=5)
        task3 = QueuedTask(task_id="task-3", task_type="review", repository_id="repo", priority=5)

        task_queue.enqueue(task1)
        task_queue.enqueue(task2)
        task_queue.enqueue(task3)

        assert task_queue.dequeue().task_id == "task-1"
        assert task_queue.dequeue().task_id == "task-2"
        assert task_queue.dequeue().task_id == "task-3"

    def test_zero_priority_at_end(self, task_queue):
        """Priority 0 tasks go to the end."""
        task_zero = QueuedTask(
            task_id="task-zero", task_type="review", repository_id="repo", priority=0
        )
        task_one = QueuedTask(
            task_id="task-one", task_type="review", repository_id="repo", priority=1
        )

        task_queue.enqueue(task_zero)
        task_queue.enqueue(task_one)

        assert task_queue.dequeue().task_id == "task-one"
        assert task_queue.dequeue().task_id == "task-zero"


# =============================================================================
# Zombie Detection
# =============================================================================


@pytest.mark.functional
class TestZombieDetection:
    """Tests for zombie task detection."""

    def test_detect_zombie_after_timeout(self, task_queue):
        """Tasks processing longer than timeout are detected as zombies."""
        task = QueuedTask(task_id="zombie", task_type="review", repository_id="repo")
        task_queue.enqueue(task)

        # Dequeue to start processing
        dequeued = task_queue.dequeue()

        # Manually set started_at to simulate time passing
        dequeued.started_at = datetime.utcnow() - timedelta(minutes=35)

        # Check for zombies with 30-minute timeout
        zombies = task_queue.get_zombie_tasks(timeout_seconds=1800)

        assert len(zombies) == 1
        assert zombies[0].task_id == "zombie"

    def test_no_zombie_within_timeout(self, task_queue):
        """Tasks within timeout are not zombies."""
        task = QueuedTask(task_id="active", task_type="review", repository_id="repo")
        task_queue.enqueue(task)
        task_queue.dequeue()

        # Just started, not a zombie
        zombies = task_queue.get_zombie_tasks(timeout_seconds=1800)

        assert len(zombies) == 0

    def test_completed_tasks_not_zombies(self, task_queue):
        """Completed tasks don't appear as zombies."""
        task = QueuedTask(task_id="done", task_type="review", repository_id="repo")
        task_queue.enqueue(task)
        dequeued = task_queue.dequeue()

        # Set old started_at but then complete
        dequeued.started_at = datetime.utcnow() - timedelta(hours=2)
        task_queue.complete("done")

        zombies = task_queue.get_zombie_tasks(timeout_seconds=1800)

        assert len(zombies) == 0


# =============================================================================
# Zombie Cleanup
# =============================================================================


@pytest.mark.functional
class TestZombieCleanup:
    """Tests for zombie cleanup behavior."""

    def test_cleanup_removes_zombies(self, task_queue):
        """Cleanup removes zombie tasks from processing."""
        task = QueuedTask(task_id="zombie", task_type="review", repository_id="repo")
        task_queue.enqueue(task)
        dequeued = task_queue.dequeue()

        # Make it a zombie
        dequeued.started_at = datetime.utcnow() - timedelta(hours=1)

        # Cleanup without requeue
        cleaned_ids = task_queue.cleanup_zombie_tasks(timeout_seconds=1800, requeue=False)

        assert "zombie" in cleaned_ids

        # Verify removed from processing
        status = task_queue.get_status()
        assert status["processing"] == 0

    def test_cleanup_requeues_zombies(self, task_queue):
        """Cleanup with requeue=True puts zombies back in queue."""
        task = QueuedTask(task_id="zombie", task_type="review", repository_id="repo", priority=5)
        task_queue.enqueue(task)
        dequeued = task_queue.dequeue()

        # Make it a zombie
        dequeued.started_at = datetime.utcnow() - timedelta(hours=1)

        # Cleanup with requeue
        cleaned_ids = task_queue.cleanup_zombie_tasks(timeout_seconds=1800, requeue=True)

        assert "zombie" in cleaned_ids

        # Verify back in queue with higher priority
        status = task_queue.get_status()
        assert status["pending"] == 1
        assert status["processing"] == 0

        # Dequeue and check priority increased
        requeued = task_queue.dequeue()
        assert requeued.task_id == "zombie"
        assert requeued.priority == 6  # Original 5 + 1
        assert requeued.started_at is not None  # Reset when dequeued again


# =============================================================================
# Task Lifecycle
# =============================================================================


@pytest.mark.functional
class TestTaskLifecycle:
    """Tests for complete task lifecycle."""

    def test_enqueue_dequeue_complete(self, task_queue):
        """Full lifecycle: enqueue → dequeue → complete."""
        task = QueuedTask(task_id="lifecycle", task_type="review", repository_id="repo")

        # Enqueue
        task_queue.enqueue(task)
        assert task_queue.size() == 1

        # Dequeue
        dequeued = task_queue.dequeue()
        assert dequeued.task_id == "lifecycle"
        assert dequeued.started_at is not None
        assert task_queue.size() == 0

        status = task_queue.get_status()
        assert status["processing"] == 1

        # Complete
        task_queue.complete("lifecycle")

        status = task_queue.get_status()
        assert status["processing"] == 0

    def test_enqueue_dequeue_fail(self, task_queue):
        """Lifecycle with failure: enqueue → dequeue → fail."""
        task = QueuedTask(task_id="failing", task_type="review", repository_id="repo")

        task_queue.enqueue(task)
        task_queue.dequeue()
        task_queue.fail("failing")

        status = task_queue.get_status()
        assert status["processing"] == 0

    def test_cancel_pending_task(self, task_queue):
        """Cancel a task that is pending (not yet processing)."""
        task = QueuedTask(task_id="cancellable", task_type="review", repository_id="repo")
        task_queue.enqueue(task)

        result = task_queue.cancel("cancellable")

        assert result is True
        assert task_queue.size() == 0

    def test_cannot_cancel_processing_task(self, task_queue):
        """Cannot cancel a task that is already processing."""
        task = QueuedTask(task_id="running", task_type="review", repository_id="repo")
        task_queue.enqueue(task)
        task_queue.dequeue()  # Start processing

        result = task_queue.cancel("running")

        assert result is False

        status = task_queue.get_status()
        assert status["processing"] == 1

    def test_cancel_nonexistent_task(self, task_queue):
        """Cancel returns False for non-existent task."""
        result = task_queue.cancel("nonexistent")

        assert result is False


# =============================================================================
# Queue Status
# =============================================================================


@pytest.mark.functional
class TestQueueStatus:
    """Tests for queue status reporting."""

    def test_status_empty_queue(self, task_queue):
        """Status for empty queue."""
        status = task_queue.get_status()

        assert status["pending"] == 0
        assert status["processing"] == 0
        assert status["pending_tasks"] == []
        assert status["processing_tasks"] == []

    def test_status_with_tasks(self, task_queue, sample_tasks):
        """Status with pending and processing tasks."""
        for task in sample_tasks:
            task_queue.enqueue(task)

        # Dequeue one to processing
        task_queue.dequeue()

        status = task_queue.get_status()

        assert status["pending"] == 2
        assert status["processing"] == 1
        assert len(status["pending_tasks"]) == 2
        assert len(status["processing_tasks"]) == 1

    def test_is_empty(self, task_queue):
        """is_empty returns correct value."""
        assert task_queue.is_empty() is True

        task = QueuedTask(task_id="test", task_type="review", repository_id="repo")
        task_queue.enqueue(task)

        assert task_queue.is_empty() is False

        task_queue.dequeue()

        assert task_queue.is_empty() is True


# =============================================================================
# Task Age Tracking
# =============================================================================


@pytest.mark.functional
class TestTaskAgeTracking:
    """Tests for task age/duration tracking."""

    def test_get_task_age(self, task_queue):
        """Get age of processing task."""
        task = QueuedTask(task_id="timed", task_type="review", repository_id="repo")
        task_queue.enqueue(task)
        task_queue.dequeue()

        age = task_queue.get_task_age("timed")

        assert age is not None
        assert age.total_seconds() >= 0
        assert age.total_seconds() < 1  # Just started

    def test_get_task_age_nonexistent(self, task_queue):
        """Get age returns None for non-existent task."""
        age = task_queue.get_task_age("nonexistent")

        assert age is None

    def test_get_task_age_pending(self, task_queue):
        """Get age returns None for pending (not yet processing) task."""
        task = QueuedTask(task_id="pending", task_type="review", repository_id="repo")
        task_queue.enqueue(task)

        age = task_queue.get_task_age("pending")

        assert age is None


# =============================================================================
# Thread Safety
# =============================================================================


@pytest.mark.functional
@pytest.mark.slow
class TestThreadSafety:
    """Tests for concurrent access safety."""

    def test_concurrent_enqueue(self, task_queue):
        """Multiple threads can enqueue safely."""
        results = []
        errors = []

        def enqueue_task(task_id):
            try:
                task = QueuedTask(
                    task_id=f"task-{task_id}",
                    task_type="review",
                    repository_id="repo",
                    priority=task_id,
                )
                task_queue.enqueue(task)
                results.append(task_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=enqueue_task, args=(i,)) for i in range(20)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 20
        assert task_queue.size() == 20

    def test_concurrent_dequeue(self, task_queue):
        """Multiple threads can dequeue safely without duplicates."""
        # Enqueue 10 tasks
        for i in range(10):
            task = QueuedTask(task_id=f"task-{i}", task_type="review", repository_id="repo")
            task_queue.enqueue(task)

        dequeued_ids = []
        lock = threading.Lock()

        def dequeue_task():
            task = task_queue.dequeue()
            if task:
                with lock:
                    dequeued_ids.append(task.task_id)

        # 15 threads trying to dequeue 10 tasks
        threads = [threading.Thread(target=dequeue_task) for _ in range(15)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have dequeued exactly 10 unique tasks
        assert len(dequeued_ids) == 10
        assert len(set(dequeued_ids)) == 10  # All unique

    def test_concurrent_enqueue_dequeue(self, task_queue):
        """Concurrent enqueue and dequeue operations."""
        enqueued = []
        dequeued = []
        lock = threading.Lock()

        def enqueue_worker():
            for i in range(5):
                task = QueuedTask(
                    task_id=f"en-{threading.current_thread().name}-{i}",
                    task_type="review",
                    repository_id="repo",
                )
                task_queue.enqueue(task)
                with lock:
                    enqueued.append(task.task_id)
                time.sleep(0.001)

        def dequeue_worker():
            for _ in range(5):
                task = task_queue.dequeue()
                if task:
                    with lock:
                        dequeued.append(task.task_id)
                    task_queue.complete(task.task_id)
                time.sleep(0.002)

        enqueue_threads = [threading.Thread(target=enqueue_worker, name=f"E{i}") for i in range(3)]
        dequeue_threads = [threading.Thread(target=dequeue_worker, name=f"D{i}") for i in range(3)]

        for t in enqueue_threads + dequeue_threads:
            t.start()
        for t in enqueue_threads + dequeue_threads:
            t.join()

        # All enqueued tasks should exist
        assert len(enqueued) == 15  # 3 threads * 5 tasks

        # Dequeued tasks should be subset of enqueued
        assert all(d in enqueued for d in dequeued)


# =============================================================================
# Max Size Behavior
# =============================================================================


@pytest.mark.functional
class TestMaxSizeBehavior:
    """Tests for queue max size enforcement."""

    def test_max_size_enforced(self):
        """Queue respects max_size limit."""
        queue = TaskQueue(max_size=5)

        for i in range(10):
            task = QueuedTask(task_id=f"task-{i}", task_type="review", repository_id="repo")
            queue.enqueue(task)

        # deque with maxlen drops oldest when full
        assert queue.size() == 5


# =============================================================================
# Global Queue Singleton
# =============================================================================


@pytest.mark.functional
class TestGlobalQueueSingleton:
    """Tests for global queue singleton."""

    def test_get_task_queue_returns_same_instance(self):
        """get_task_queue returns same instance on multiple calls."""
        queue1 = get_task_queue()
        queue2 = get_task_queue()

        assert queue1 is queue2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
