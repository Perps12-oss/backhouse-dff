# 🚀 Migration Guide: main.py → main_improved.py

## Overview

This guide helps you migrate from the current `main.py` to the improved version while maintaining functionality.

---

## ⚡ Quick Start (Recommended Approach)

### Option 1: Side-by-Side Testing (Safest)

1. **Keep both files:**
   ```
   main.py          # Your current working version
   main_improved.py # The improved version
   ```

2. **Test the improved version:**
   ```bash
   python main_improved.py
   ```

3. **Once validated, replace:**
   ```bash
   # Backup original
   cp main.py main_backup.py
   
   # Replace with improved version
   cp main_improved.py main.py
   ```

### Option 2: Gradual Migration

Migrate features one at a time from `main_improved.py` to your `main.py`.

---

## 📋 Feature-by-Feature Migration

### 1. Logging System (High Priority)

**What to Add:**
```python
# At the top of main.py, replace print setup with:
from cerebro.services.logger import get_logger, configure, flush_all_handlers

# Replace the global logger
logger = get_logger("main")

# Replace all print_step() calls
# OLD:
print_step("Importing PySide6...")

# NEW:
logger.info("Importing PySide6...")
```

**Find and Replace:**
- `print_step(` → `logger.info(`
- `print(` → `logger.info(` (for informational messages)
- `print(f"❌` → `logger.error(`
- `print(f"⚠️` → `logger.warning(`

---

### 2. Configuration Integration (High Priority)

**Add Configuration Loading:**
```python
from cerebro.services.config import load_config, save_config

# In main() function, before creating Qt app:
try:
    config = load_config()
    logger.info(f"Configuration loaded")
except Exception as e:
    logger.warning(f"Using default config: {e}")
    config = AppConfig()
```

**Use Config Values:**
```python
# Replace hardcoded values:
# OLD:
APP_NAME = "CEREBRO"
APP_VERSION = "5.0.0"

# NEW:
# Use from config or define AppMetadata class
app.setApplicationName(config.app_name or "CEREBRO")
```

---

### 3. Crash Handler Enhancement (Medium Priority)

**Improve Crash Handler:**
```python
def install_crash_handlers() -> None:
    """Install enhanced crash handler."""
    original_excepthook = sys.excepthook
    
    def crash_handler(exc_type, exc_value, exc_traceback):
        # Use logger instead of print
        logger.critical("=" * 60)
        logger.critical("CEREBRO CRASHED!")
        logger.critical("=" * 60)
        logger.exception("Uncaught exception", 
                        exc_info=(exc_type, exc_value, exc_traceback))
        
        # Save crash log (keep existing code)
        try:
            crash_file = ROOT_DIR / "crash_report.txt"
            with open(crash_file, 'w', encoding='utf-8') as f:
                f.write(f"CEREBRO Crash Report\n")
                f.write(f"Version: {APP_VERSION}\n")
                f.write(f"Python: {sys.version}\n")
                f.write(f"Time: {datetime.datetime.now()}\n\n")
                traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
            logger.info(f"Crash log saved to: {crash_file}")
        except Exception:
            pass
        
        # Flush logs before exit
        flush_all_handlers()
        pause("Crash detected. Press ENTER to exit...")
        original_excepthook(exc_type, exc_value, exc_traceback)
    
    sys.excepthook = crash_handler
```

---

### 4. Dependency Checking (Medium Priority)

**Add Before PySide6 Import:**
```python
def check_dependencies():
    """Check if all dependencies are available."""
    errors = []
    
    # Check PySide6
    try:
        import PySide6
        logger.info(f"PySide6 available: {PySide6.__version__}")
    except ImportError:
        errors.append("PySide6 not installed. Run: pip install PySide6")
    
    # Check Python version
    if sys.version_info < (3, 8):
        errors.append(f"Python 3.8+ required, found {sys.version_info.major}.{sys.version_info.minor}")
    
    if errors:
        for error in errors:
            logger.error(error)
        return False
    return True

# In main():
if not check_dependencies():
    pause("Dependency check failed")
    return 1
```

---

### 5. Performance Monitoring (Optional)

**Add Startup Timing:**
```python
import time

class StartupTimer:
    def __init__(self):
        self.start = time.time()
        self.steps = []
    
    def step(self, name):
        elapsed = time.time() - self.start
        self.steps.append((name, elapsed))
        logger.info(f"✓ {name} ({elapsed:.3f}s)")

# In main():
timer = StartupTimer()

# After each major step:
timer.step("PySide6 imported")
timer.step("Qt application created")
# etc.
```

---

### 6. Window State Persistence (Optional)

**Save Window Geometry:**
```python
# Before app.exec():
if config and config.window_geometry:
    try:
        window.restoreGeometry(config.window_geometry)
    except Exception as e:
        logger.warning(f"Could not restore window geometry: {e}")

# After app.exec(), before return:
if config:
    try:
        config.window_geometry = window.saveGeometry()
        config.window_state = window.saveState()
        save_config(config)
        logger.info("Window state saved")
    except Exception as e:
        logger.warning(f"Could not save window state: {e}")
```

---

## 🔄 Step-by-Step Migration Process

### Week 1: Core Improvements

**Day 1-2: Logging**
- [ ] Import logger module
- [ ] Replace all print statements
- [ ] Test logging output
- [ ] Verify log files are created

**Day 3-4: Configuration**
- [ ] Add config loading
- [ ] Replace hardcoded values
- [ ] Test config save/load
- [ ] Verify settings persist

**Day 5: Testing**
- [ ] Run full application test
- [ ] Check all features work
- [ ] Review log output
- [ ] Fix any issues

---

### Week 2: Enhancements

**Day 1-2: Crash Handler**
- [ ] Enhance crash handler with logging
- [ ] Add more crash metadata
- [ ] Test crash recovery
- [ ] Verify crash reports

**Day 3-4: Dependencies & Environment**
- [ ] Add dependency checker
- [ ] Add environment validation
- [ ] Improve error messages
- [ ] Test error scenarios

**Day 5: Polish**
- [ ] Add performance monitoring
- [ ] Add window state persistence
- [ ] Code cleanup
- [ ] Documentation update

---

## 🧪 Testing Checklist

Before switching to improved version:

### Functional Tests
- [ ] Application starts successfully
- [ ] Main window appears
- [ ] All features work (scanning, etc.)
- [ ] Settings are saved
- [ ] Application closes cleanly

### Error Handling Tests
- [ ] Test without PySide6 (should show clear error)
- [ ] Test with corrupted config (should fallback)
- [ ] Test crash scenarios (should log properly)
- [ ] Test with no write permissions

### Performance Tests
- [ ] Measure startup time
- [ ] Check memory usage
- [ ] Verify responsiveness
- [ ] Compare with old version

### Log Tests
- [ ] Verify logs are created
- [ ] Check log rotation
- [ ] Verify crash logs
- [ ] Check log readability

---

## 🔧 Troubleshooting Common Issues

### Issue 1: "Module 'logger' not found"

**Solution:**
```python
# Ensure cerebro package is in Python path
import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))
```

---

### Issue 2: Config File Not Loading

**Solution:**
```python
# Check config directory exists and is writable
config_dir = Path.home() / ".cerebro"
config_dir.mkdir(parents=True, exist_ok=True)

# Add error handling
try:
    config = load_config()
except Exception as e:
    logger.warning(f"Config load failed: {e}, using defaults")
    config = AppConfig()
```

---

### Issue 3: Logs Not Appearing

**Solution:**
```python
# Ensure logger is configured
from cerebro.services.logger import configure
import logging

configure(level=logging.DEBUG)  # For debugging
```

---

### Issue 4: Window Geometry Not Restoring

**Solution:**
```python
# Check if data is valid
if config.window_geometry and len(config.window_geometry) > 0:
    try:
        window.restoreGeometry(config.window_geometry)
    except Exception as e:
        logger.warning(f"Invalid geometry data: {e}")
```

---

## 🎯 Benefits After Migration

### Before
- ❌ Print statements only
- ❌ Hardcoded settings
- ❌ Basic error handling
- ❌ No performance tracking
- ❌ Window position not saved

### After
- ✅ Professional logging system
- ✅ Configurable settings
- ✅ Comprehensive error handling
- ✅ Startup performance monitoring
- ✅ Window state persistence
- ✅ Better crash reports
- ✅ Dependency validation
- ✅ Environment checks

---

## 📊 Comparison Table

| Feature | main.py | main_improved.py |
|---------|---------|------------------|
| Logging | Print statements | Full logger module |
| Configuration | Hardcoded | Config file |
| Error Messages | Basic | Detailed + solutions |
| Crash Handler | Simple | Enhanced + metadata |
| Dependencies | PySide6 only | Comprehensive check |
| Performance | No tracking | Full monitoring |
| Window State | Not saved | Fully persistent |
| Code Organization | Procedural | Class-based |
| Testability | Difficult | Easy |
| Maintainability | Medium | High |

---

## 🚦 Migration Decision Tree

```
Start
  |
  ├─ Need quick fix? 
  │    └─ Yes → Keep current, apply patches
  │    └─ No → Continue
  |
  ├─ Have time to test?
  │    └─ Yes → Use main_improved.py
  │    └─ No → Gradual migration
  |
  ├─ Production environment?
  │    └─ Yes → Test thoroughly first
  │    └─ No → Try improved version now
  |
  └─ Final Decision
       ├─ Option A: Full replacement (fastest)
       ├─ Option B: Gradual migration (safest)
       └─ Option C: Cherry-pick features (flexible)
```

---

## 📚 Additional Resources

1. **main_improved.py** - Complete improved version
2. **CODE_REVIEW_IMPROVEMENTS.md** - Detailed improvement guide
3. **cerebro/services/logger.py** - Logging module reference
4. **cerebro/services/config.py** - Configuration module reference

---

## ✅ Migration Success Criteria

Migration is successful when:

1. **Application starts without errors**
2. **All features work as before**
3. **Log files are created and useful**
4. **Configuration persists correctly**
5. **Error messages are clear**
6. **Performance is same or better**
7. **Window state is saved/restored**
8. **Code is more maintainable**

---

## 🎓 Next Steps After Migration

1. **Add unit tests**
2. **Create user documentation**
3. **Implement CLI arguments**
4. **Add auto-update feature**
5. **Create installer/package**
6. **Add splash screen**
7. **Implement themes**
8. **Add keyboard shortcuts**

---

**Good luck with the migration! The improved version will make your application more professional, maintainable, and user-friendly.**
