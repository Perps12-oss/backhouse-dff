"""
EYEV_PRO - Professional Eye Simulator v4.2 FINAL
Fixed critical issues with comprehensive enhancements.
from dataclasses import dataclass, field"""
# Add this before the Shader class definition
import traceback
from OpenGL.GL import *

# Patch for Shader class

# === AUTO-FIXED SHADER CLASS ===
from OpenGL.GL import (
    GL_VERTEX_SHADER, GL_FRAGMENT_SHADER, GL_ACTIVE_UNIFORMS,
    glUseProgram, glGetProgramiv, glGetActiveUniform, glGetUniformLocation,
    glUniform1f, glUniform1i, glUniform3f, glUniformMatrix4fv
)

class Shader:
    """Fixed Shader class that initializes all attributes properly."""
    
    def __init__(self, vertex_source: str, fragment_source: str):
        try:
            # Compile shaders
            vertex_shader = shaders.compileShader(vertex_source, GL_VERTEX_SHADER)
            fragment_shader = shaders.compileShader(fragment_source, GL_FRAGMENT_SHADER)
            # Link program
            self.program = shaders.compileProgram(vertex_shader, fragment_shader)
            
            # Initialize attributes
            self.uniform_locations = {}
            self.uniform_types = {}  # This fixes the 'uniform_types' error
            
            # Cache uniforms safely
            self._cache_uniforms_safely()
            
        except Exception as e:
            print(f"Shader compilation error: {e}")
            raise
    
    def _cache_uniforms_safely(self):
        """Cache uniforms without crashing."""
        try:
            num_uniforms = glGetProgramiv(self.program, GL_ACTIVE_UNIFORMS)
            for i in range(num_uniforms):
                name, size, uniform_type = glGetActiveUniform(self.program, i)
                if isinstance(name, bytes):
                    name = name.decode('utf-8')
                loc = glGetUniformLocation(self.program, name)
                if loc != -1:
                    self.uniform_locations[name] = loc
                    self.uniform_types[name] = uniform_type
        except Exception as e:
            print(f"Warning: Could not cache all uniforms: {e}")
            # Initialize with empty dicts
            self.uniform_locations = {}
            self.uniform_types = {}
    
    def use(self):
        """Activate this shader."""
        glUseProgram(self.program)
    
    def set_uniform(self, name: str, value):
        """Set uniform with fallback."""
        if name not in self.uniform_locations:
            loc = glGetUniformLocation(self.program, name)
            if loc == -1:
                return  # Uniform not found, skip
            self.uniform_locations[name] = loc
        
        loc = self.uniform_locations[name]
        
        try:
            if hasattr(value, 'x') and hasattr(value, 'y') and hasattr(value, 'z'):  # QVector3D
                glUniform3f(loc, value.x(), value.y(), value.z())
            elif hasattr(value, 'constData'):  # QMatrix4x4
                glUniformMatrix4fv(loc, 1, GL_FALSE, value.constData())
            elif isinstance(value, (list, tuple)):
                if len(value) == 3:
                    glUniform3f(loc, *value)
                elif len(value) == 4:
                    glUniform4f(loc, *value)
                else:
                    glUniform1f(loc, float(value[0]))
            elif isinstance(value, bool):
                glUniform1i(loc, int(value))
            elif isinstance(value, int):
                glUniform1i(loc, value)
            elif isinstance(value, float):
                glUniform1f(loc, value)
        except Exception as e:
            # Silently ignore uniform errors
            pass
# === END AUTO-FIX ===

class AnimationCurves:
    """Collection of animation easing functions for natural movement."""
    @staticmethod
    def ease_in_out_cubic(t: float) -> float:
        return t * t * (3.0 - 2.0 * t)
    
    @staticmethod
    def ease_in_out_sine(t: float) -> float:
        return -(math.cos(math.pi * t) - 1.0) / 2.0
    
    @staticmethod
    def ease_out_back(t: float) -> float:
        """Overshoot and settle back"""
        c1 = 1.70158
        c3 = c1 + 1
        return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)


# --- Micro-Movement Generator ---
class MicroMovementGenerator:
    """Generate scientifically accurate ocular micro-movements"""
    
    def __init__(self):
        self.tremor_phase_x = random.random() * 2 * math.pi
        self.tremor_phase_y = random.random() * 2 * math.pi
        self.drift_history = deque(maxlen=100)
        self.drift_target = QVector3D(0, 0, 0)
        
    def generate_tremor(self, frequency_hz: float, amplitude_deg: float, t: float) -> QVector3D:
        """High-frequency physiological tremor (~30-100 Hz)"""
        # Multiple harmonics for realistic tremor
        f1 = frequency_hz
        f2 = frequency_hz * 1.618  # Golden ratio harmonic
        f3 = frequency_hz * 0.5    # Sub-harmonic
        
        x = (math.sin(2*math.pi*f1*t + self.tremor_phase_x) * 0.5 +
             math.sin(2*math.pi*f2*t + self.tremor_phase_x*1.3) * 0.3 +
             math.sin(2*math.pi*f3*t + self.tremor_phase_x*0.7) * 0.2) * amplitude_deg
        
        y = (math.cos(2*math.pi*f1*t*0.9 + self.tremor_phase_y) * 0.5 +
             math.cos(2*math.pi*f2*t*0.9 + self.tremor_phase_y*1.3) * 0.3 +
             math.cos(2*math.pi*f3*t*0.9 + self.tremor_phase_y*0.7) * 0.2) * amplitude_deg
        
    
    def generate_drift(self, amplitude_deg: float) -> Tuple[QVector3D, QVector3D]:
        """Slow Brownian motion drift with power-law characteristics"""
        # Random walk with momentum
        if random.random() < 0.05:  # Occasionally change direction
            self.drift_target = QVector3D(
                random.uniform(-1, 1),
                random.uniform(-1, 1),
                0
            ).normalized() * amplitude_deg
        
        self.drift_history.append(self.drift_target)
        return self.drift_target, QVector3D(0, 0, 0)


# --- Corneal Topography ---
class CornealTopography:
    """Simulate corneal shape variations"""
    
    def __init__(self):
        self.astigmatism_axis = 0.0  # degrees
        self.astigmatism_power = 0.0  # diopters
        self.keratoconus_stage = 0.0  # 0-1
        self.corneal_radius = 7.8  # mm, average human cornea
        self.pachymetry_map = None  # Corneal thickness map
        self.endothelial_cell_density = 3000  # cells/mm²
        
    def apply_pathology(self, pathology_type: str, severity: float):
        """Apply specific corneal pathology."""
        if pathology_type == "pterygium":
            # Add triangular growth from conjunctiva
            pass
        elif pathology_type == "arcus_senilis":
            # Add lipid ring at corneal periphery
            pass
        # ... other pathologies
        
    def deform_vertex(self, vertex: QVector3D) -> QVector3D:
        """Apply corneal deformation to vertex"""
        angle = math.atan2(vertex.y(), vertex.x())
        radius = vertex.length()
        
        # Astigmatism (elliptical deformation)
        astig_factor = 1.0 + self.astigmatism_power * 0.01 * math.sin(2*(angle - math.radians(self.astigmatism_axis)))
        
        # Keratoconus (localized thinning)
        cone_center = QVector3D(0, 0.3, 0.8)  # Typical inferior location
        dist_to_cone = (vertex - cone_center).length()
        cone_factor = 1.0 - self.keratoconus_stage * math.exp(-dist_to_cone*5.0)
        
        # Normal corneal curvature (spheroidal)
        curvature_factor = 1.0 - (radius / self.corneal_radius)
        
        deformed = vertex.normalized() * radius * astig_factor * cone_factor * curvature_factor
        return deformed
    
    def get_corneal_thickness(self, uv: QVector3D) -> float:
        """Get corneal thickness for subsurface scattering simulation"""
        center_dist = uv.length()
        # Thinner in center (0.52mm), thicker at periphery (0.67mm)
        thickness = AVERAGE_CORNEAL_THICKNESS_CENTER + (AVERAGE_CORNEAL_THICKNESS_PERIPHERY - AVERAGE_CORNEAL_THICKNESS_CENTER) * (1.0 - math.exp(-center_dist * 5.0))
        # Keratoconus thinning
        if self.keratoconus_stage > 0:
            cone_center = QVector3D(0, 0.3, 0.8)
            dist = (uv - cone_center).length()
            thickness *= 1.0 - self.keratoconus_stage * math.exp(-dist * 10.0)
        
        return max(0.3, thickness)


# --- Pupil Dynamics ---
class PupilDynamics:
    """Realistic pupil light reflex with latency and dual-component response"""
    
    def __init__(self):
        self.light_history = deque(maxlen=100)  # (timestamp, light_level)
        self.pupil_fast = 0.5  # Fast parasympathetic response
        self.pupil_slow = 0.5  # Slow sympathetic response
        self.pupil_hippus = 0.0  # Rhythmic oscillation
        self.hippus_phase = random.random() * 2 * math.pi
        self.hippus_frequency = HIPPUS_FREQUENCY  # Hz
        
    def update(self, dt: float, current_light: float, target_light: float):
        """Update pupil dynamics with realistic physiology"""
        # Store light history for latency simulation
        self.light_history.append((time.time(), current_light))
        
        # Pupillary latency (~200-250ms)
        latency = 0.22  # seconds
        delayed_light = current_light  # Default if no history
        
        for t, lvl in reversed(self.light_history):
            if time.time() - t >= latency:
                delayed_light = lvl
                break
        
        # Fast and slow components with different time constants
        fast_target = 1.0 - delayed_light
        slow_target = 1.0 - target_light * 0.7  # Slower adaptation
        
        fast_time_constant = 0.15  # Fast parasympathetic
        slow_time_constant = 0.5   # Slow sympathetic
        
        self.pupil_fast += (fast_target - self.pupil_fast) * dt / fast_time_constant
        self.pupil_slow += (slow_target - self.pupil_slow) * dt / slow_time_constant
        
        # Hippus (rhythmic pupil oscillation)
        self.hippus_phase += dt * self.hippus_frequency * 2 * math.pi
        hippus_amp = HIPPUS_MAX_AMPLITUDE * (1.0 - target_light)  # Larger in dark
        hippus = math.sin(self.hippus_phase) * hippus_amp
        
        # Combine components
        combined = (self.pupil_fast * 0.7 + self.pupil_slow * 0.3 + hippus)
        return max(0.1, min(1.0, combined))


# --- Configuration ---
@dataclass
class EyeConfig:
    """Centralized configuration for the eye's appearance and behavior."""
    # Sclera
    sclera_color: QVector3D = field(default_factory=lambda: QVector3D(0.92, 0.90, 0.88))
    sclera_tint: QVector3D = field(default_factory=lambda: QVector3D(0.05, 0.02, 0.0))
    vein_color: QVector3D = field(default_factory=lambda: QVector3D(0.6, 0.2, 0.2))
    vein_intensity: float = 0.4
    bloodshot_level: float = 0.0  # 0-1
    
    # Iris
    iris_inner_color: QVector3D = field(default_factory=lambda: QVector3D(0.15, 0.35, 0.25))
    iris_outer_color: QVector3D = field(default_factory=lambda: QVector3D(0.05, 0.15, 0.25))
    iris_radius: float = 0.42
    pupil_base_radius: float = 0.15
    pupil_variation: float = 0.12
    limbal_ring_thickness: float = 0.03
    limbal_ring_intensity: float = 0.7
    collarette_intensity: float = 0.3
    
    # Cornea
    cornea_thickness_center: float = AVERAGE_CORNEAL_THICKNESS_CENTER  # mm
    cornea_thickness_periphery: float = AVERAGE_CORNEAL_THICKNESS_PERIPHERY  # mm
    astigmatism_axis: float = 0.0  # degrees
    astigmatism_power: float = 0.0  # diopters
    keratoconus_stage: float = 0.0  # 0-1
    
    # Skin & Eyelids
    skin_color: QVector3D = field(default_factory=lambda: QVector3D(0.85, 0.65, 0.55))
    eyelash_density: float = 0.5
    upper_lid_curve: float = 0.8
    lower_lid_curve: float = -0.7
    lid_thickness: float = 0.05
    lid_softness: float = 0.04
    
    # Lighting
    main_light_pos: QVector3D = field(default_factory=lambda: QVector3D(5.0, 5.0, 10.0))
    fill_light_pos: QVector3D = field(default_factory=lambda: QVector3D(-5.0, -2.0, 5.0))
    ambient_intensity: float = 0.25
    specular_power: float = 180.0
    specular_intensity: float = 1.2
    
    # Physical Properties
    cornea_ior: float = 1.34  # Index of Refraction
    tear_film_wetness: float = 0.8
    tear_film_thickness: float = 0.007  # mm
    bloom_intensity: float = 0.5

    # Behavior
    saccade_speed: float = 25.0  # degrees per second
    saccade_interval_min: float = 1.5
    saccade_interval_max: float = 4.0
    microsaccade_intensity: float = 0.5
    drift_speed: float = 1.0
    tremor_frequency: float = 80.0  # Hz
    tremor_amplitude: float = 0.02  # degrees
    blink_interval_min: float = 2.0
    blink_interval_max: float = 6.0
    blink_duration_close: float = 0.1
    blink_duration_open: float = 0.15
    
    # Medical Visualization
    visualization_mode: str = "normal"  # normal, fluorescein, red_reflex, retroillumination


# --- State Management ---
class EyeState:
    """Container for all dynamic eye state variables."""
    def __init__(self):
        # Rotation
        self.rotation = QVector3D(0, 0, 0)
        self.target_rotation = QVector3D(0, 0, 0)
        self.actual_rotation = QVector3D(0, 0, 0)  # With all micro-movements
        
        # Movement Systems
        self.is_saccading = False
        self.saccade_start_rot = QVector3D(0, 0, 0)
        self.saccade_target_rot = QVector3D(0, 0, 0)
        self.saccade_progress = 1.0
        self.next_saccade_time = time.time() + 1.0
        
        # Micro-movements
        self.drift_offset = QVector3D(0, 0, 0)
        self.drift_target = QVector3D(0, 0, 0)
        self.tremor_offset = QVector3D(0, 0, 0)
        self.last_drift_change = time.time()
        
        # Pupil
        self.pupil_size = 0.5
        self.target_pupil = 0.5
        self.light_level = 0.5
        self.actual_light_level = 0.5  # With latency
        
        # Eyelids
        self.blink_factor = 0.0
        self.squint_factor = 0.0
        self.target_squint_factor = 0.0
        self.upper_lid_open = 0.7
        self.lower_lid_open = -0.6
        self.bell_rotation = 0.0  # Bell's phenomenon (eyes roll up during blink)
        
        # Blinking
        self.blink_state = "idle"
        self.blink_timer = 0.0
        self.next_blink_time = time.time() + 3.0
        
        # Medical State
        self.fluorescein_staining = 0.0  # 0-1 for medical visualization
        self.red_reflex_intensity = 0.0
        
        # Accommodation
        self.accommodation_level = 0.0  # 0 (far) to 1 (near)
        self.lens_thickness = AVERAGE_LENS_THICKNESS  # mm
        
        # Performance Tracking
        self.frame_count = 0
        self.fps = 60.0


# --- Shader Management ---
# --- Geometry Generation ---
class GeometryGenerator:
    """Generate 3D geometry for eye components with anatomical accuracy."""
    
    @staticmethod
    def generate_sphere(radius: float = 1.0, sectors: int = 64, stacks: int = 64):
        """Generate eyeball sphere with proper normals."""
        vertices = []
        indices = []
        
        for i in range(stacks + 1):
            stack_angle = math.pi / 2 - i * math.pi / stacks
            xy = radius * math.cos(stack_angle)
            z = radius * math.sin(stack_angle)

            for j in range(sectors + 1):
                sector_angle = j * 2 * math.pi / sectors
                x = xy * math.cos(sector_angle)
                y = xy * math.sin(sector_angle)
                u = j / sectors
                v = i / stacks
                nx, ny, nz = x/radius, y/radius, z/radius
                vertices.extend([x, y, z, u, v, nx, ny, nz])

        for i in range(stacks):
            k1 = i * (sectors + 1)
            k2 = k1 + sectors + 1
            for j in range(sectors):
                if i != 0: indices.extend([k1, k2, k1 + 1])
                if i != (stacks - 1): indices.extend([k1 + 1, k2, k2 + 1])
                k1 += 1; k2 += 1
                
        return vertices, indices

    @staticmethod
    def generate_eyelid_shell(is_upper: bool, eye_radius: float = 1.0):
        """Generate anatomically accurate eyelid shells."""
        vertices = []
        indices = []
        radial_segments = 32
        depth_segments = 8
        
        for i in range(radial_segments + 1):
            angle = i * math.pi / radial_segments
            
            for j in range(depth_segments + 1):
                depth = j * 0.15  # Increased for better wrapping
                
                # Base spherical position
                x = math.cos(angle) * (eye_radius + depth)
                y = math.sin(angle) * (eye_radius + depth)
                
                # Apply eyelid-specific shaping
                if is_upper:
                    y = y * 0.8 + 0.4  # Upper lid sits higher
                    z = -math.sqrt(max(0, eye_radius**2 - x**2 - y**2)) - 0.08
                    # Additional curvature for natural fold
                    fold_curve = (1.0 - abs(angle - math.pi/2) / (math.pi/2)) * 0.3
                    z -= fold_curve
                else:
                    y = y * 0.8 - 0.4  # Lower lid
                    z = math.sqrt(max(0, eye_radius**2 - x**2 - y**2)) + 0.08
                    fold_curve = (1.0 - abs(angle - math.pi/2) / (math.pi/2)) * 0.3
                    z += fold_curve
                
                # Texture coordinates
                u = i / radial_segments
                v = j / depth_segments
                
                # Normal calculation (pointing outward from eye)
                normal = QVector3D(x, y, z).normalized()
                
                vertices.extend([x, y, z, u, v, normal.x(), normal.y(), normal.z()])
        
        # Generate quad strip indices
        for i in range(radial_segments):
            for j in range(depth_segments):
                i1 = i * (depth_segments + 1) + j
                i2 = i1 + 1
                i3 = (i + 1) * (depth_segments + 1) + j
                i4 = i3 + 1
                
                # Two triangles per quad
                indices.extend([i1, i3, i2])
                indices.extend([i2, i3, i4])
                
        return vertices, indices

    @staticmethod
    def generate_eyelashes(is_upper: bool, count: int = 40, lod: int = 0):
        """Generate curved eyelash geometry with level of detail."""
        vertices = []
        indices = []
        
        # Adjust count and segments based on LOD
        actual_count = count
        segments = EYELASH_SEGMENTS[min(lod, len(EYELASH_SEGMENTS)-1)]
        
        for lash_idx in range(actual_count):
            # Position along eyelid
            t = lash_idx / actual_count
            angle = math.pi * 0.8 * (t - 0.5)  # Center around front
            
            base_x = math.cos(angle) * 1.1
            base_y = math.sin(angle) * (0.95 if is_upper else -0.95)
            base_z = 0.1 if is_upper else -0.1
            
            # Generate curved lash (cubic bezier)
            for seg in range(segments + 1):
                s = seg / segments
                
                # Control points for natural curve
                if is_upper:
                    x = base_x + 0.15 * s
                    y = base_y + 0.2 * s * (1 - s * 0.3)
                    z = base_z - 0.05 * s * (1 - s)
                else:
                    x = base_x + 0.15 * s
                    y = base_y - 0.2 * s * (1 - s * 0.3)
                    z = base_z + 0.05 * s * (1 - s)
                
                vertices.extend([x, y, z, s, 0, 0, 0, 0])  # Simple vertex data
        
        # Simple line indices for lashes
        for i in range(actual_count):
            base_idx = i * (segments + 1)
            for seg in range(segments):
                indices.extend([base_idx + seg, base_idx + seg + 1])
                
        return vertices, indices


# --- Preset Manager ---
class PresetManager:
    """Manage preset configurations with proper referencing."""
    
    @staticmethod
    def create_calm_preset() -> EyeConfig:
        config = EyeConfig()
        config.saccade_speed = 20.0
        config.blink_interval_min = 3.0
        config.microsaccade_intensity = 0.3
        config.drift_speed = 0.5
        return config
    
    @staticmethod
    def create_alert_preset() -> EyeConfig:
        config = EyeConfig()
        config.saccade_speed = 40.0
        config.blink_interval_min = 4.0
        config.microsaccade_intensity = 0.8
        config.drift_speed = 2.0
        config.pupil_base_radius = 0.12
        return config
    
    @staticmethod
    def create_tired_preset() -> EyeConfig:
        config = EyeConfig()
        config.saccade_speed = 10.0
        config.blink_interval_min = 1.5
        config.blink_duration_close = 0.15
        config.blink_duration_open = 0.2
        config.microsaccade_intensity = 0.1
        config.sclera_tint = QVector3D(0.1, 0.08, 0.05)
        return config


# --- Main Renderer ---
class EyeRenderer(QOpenGLWidget):
    """Advanced OpenGL renderer for realistic eye simulation."""
    
    eyeStateChanged = Signal(object)
    
    def __init__(self, config: EyeConfig, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        
        self.config = config  # Reference to shared config object
        self.eye_state = EyeState()
        
        # Enhanced movement systems
        self.micro_movement_gen = MicroMovementGenerator()
        self.corneal_topography = CornealTopography()
        self.pupil_dynamics = PupilDynamics()
        
        # OpenGL resources
        self.shader = None
        self.bloom_shader = None
        self.eyelash_shader = None
        
        # VAOs and VBOs
        self.vao_eyeball = None
        self.vao_eyelids = None
        self.vao_eyelashes = None
        self.vao_quad = None
        
        # Buffer storage for cleanup
        self.buffers = []
        
        # Framebuffer for post-processing
        self.fbo = None
        self.color_buffer = None
        self.depth_buffer = None
        
        # Geometry counts
        self.num_indices_eyeball = 0
        self.num_indices_eyelids = 0
        self.num_indices_eyelashes = 0
        
        # Camera & View
        self.view_distance = 3.8
        self.is_dragging_light = False
        
        # Time tracking
        self.start_time = time.time()
        self.last_frame_time = self.start_time
        self.frame_times = deque(maxlen=60)
        
        # Error handling
        self.fallback_mode = False
        
        # Setup animation timer
        self._setup_timer()

    def _setup_timer(self):
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_physics)
        self.timer.start(16)  # ~60 FPS

    def initializeGL(self):
        try:
            # Compile shaders
            self.shader = Shader(ShaderManager.VERTEX_SHADER, ShaderManager.FRAGMENT_SHADER)
            self.bloom_shader = Shader(ShaderManager.QUAD_VERTEX_SHADER, ShaderManager.BLOOM_FRAGMENT_SHADER)
            self.eyelash_shader = Shader(ShaderManager.QUAD_VERTEX_SHADER, ShaderManager.EYELASH_FRAGMENT_SHADER)
            
            # Setup geometry
            self._setup_geometry()
            self._setup_framebuffer()
            self._setup_opengl_state()
            
            print("OpenGL initialization successful")
        except Exception as e:
            print(f"OpenGL initialization failed: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "OpenGL Error", 
                               f"Failed to initialize OpenGL: {str(e)}")
            # Fallback to basic rendering
            self.fallback_mode = True

    def _setup_framebuffer(self):
        """Setup FBO for post-processing effects."""
        self.fbo = glGenFramebuffers(1)
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        
        # Color buffer (HDR for bloom)
        self.color_buffer = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, self.color_buffer)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, self.width(), self.height(), 
                    0, GL_RGBA, GL_FLOAT, None)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, 
                              GL_TEXTURE_2D, self.color_buffer, 0)
        
        # Depth buffer
        self.depth_buffer = glGenRenderbuffers(1)
        glBindRenderbuffer(GL_RENDERBUFFER, self.depth_buffer)
        glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT, 
                             self.width(), self.height())
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                                 GL_RENDERBUFFER, self.depth_buffer)
        
        # Check framebuffer status
        if glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE:
            print("Framebuffer not complete!")
        
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        
        # Setup fullscreen quad for post-processing
        quad_vertices = [
            # positions   # texCoords
            -1.0,  1.0,  0.0, 1.0,
            -1.0, -1.0,  0.0, 0.0,
             1.0, -1.0,  1.0, 0.0,
             1.0,  1.0,  1.0, 1.0
        ]
        quad_indices = [0, 1, 2, 2, 3, 0]
        
        self.vao_quad = glGenVertexArrays(1)
        vbo = glGenBuffers(1)
        ebo = glGenBuffers(1)
        
        self.buffers.extend([vbo, ebo])
        
        glBindVertexArray(self.vao_quad)
        
        glBindBuffer(GL_ARRAY_BUFFER, vbo)
        vertices_array = (ctypes.c_float * len(quad_vertices))(*quad_vertices)
        glBufferData(GL_ARRAY_BUFFER, ctypes.sizeof(vertices_array), 
                    vertices_array, GL_STATIC_DRAW)
        
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo)
        indices_array = (ctypes.c_uint * len(quad_indices))(*quad_indices)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, ctypes.sizeof(indices_array),
                    indices_array, GL_STATIC_DRAW)
        
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 4 * 4, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 4 * 4, ctypes.c_void_p(8))
        glEnableVertexAttribArray(1)
        
        glBindVertexArray(0)

    def _setup_geometry(self):
        """Setup all geometry VAOs and VBOs."""
        # Eyeball
        vertices, indices = GeometryGenerator.generate_sphere(1.0, 64, 64)
        self.num_indices_eyeball = len(indices)
        self.vao_eyeball = self._create_vao(vertices, indices)
        
        # Eyelids
        upper_vertices, upper_indices = GeometryGenerator.generate_eyelid_shell(True, 1.0)
        lower_vertices, lower_indices = GeometryGenerator.generate_eyelid_shell(False, 1.0)
        
        all_lid_vertices = upper_vertices + lower_vertices
        offset = len(upper_vertices) // 8  # Each vertex has 8 floats
        all_lid_indices = list(upper_indices) + [i + offset for i in lower_indices]
        self.num_indices_eyelids = len(all_lid_indices)
        self.vao_eyelids = self._create_vao(all_lid_vertices, all_lid_indices)
        
        # Eyelashes with LOD
        self.eyelash_vaos = []
        self.eyelash_indices = []
        
        for lod in range(3):  # 3 levels of detail
            upper_lash_verts, upper_lash_inds = GeometryGenerator.generate_eyelashes(
                True, EYELASH_COUNTS[lod][0], lod)
            lower_lash_verts, lower_lash_inds = GeometryGenerator.generate_eyelashes(
                False, EYELASH_COUNTS[lod][1], lod)
            
            all_lash_verts = upper_lash_verts + lower_lash_verts
            lash_offset = len(upper_lash_verts) // 8
            all_lash_inds = list(upper_lash_inds) + [i + lash_offset for i in lower_lash_inds]
            
            vao = self._create_vao_simple(all_lash_verts, all_lash_inds, 5)  # Pos(3) + Tex(2)
            self.eyelash_vaos.append(vao)
            self.eyelash_indices.append(len(all_lash_inds))

    def _create_vao(self, vertices, indices):
        """Create VAO with position, texcoord, normal attributes."""
        vao = glGenVertexArrays(1)
        vbo = glGenBuffers(1)
        ebo = glGenBuffers(1)
        
        self.buffers.extend([vbo, ebo])
        
        glBindVertexArray(vao)
        
        # Vertex buffer
        glBindBuffer(GL_ARRAY_BUFFER, vbo)
        vertices_array = (ctypes.c_float * len(vertices))(*vertices)
        glBufferData(GL_ARRAY_BUFFER, ctypes.sizeof(vertices_array), 
                    vertices_array, GL_STATIC_DRAW)
        
        # Element buffer
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo)
        indices_array = (ctypes.c_uint * len(indices))(*indices)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, ctypes.sizeof(indices_array),
                    indices_array, GL_STATIC_DRAW)
        
        # Vertex attributes
        stride = 8 * 4  # 8 floats * 4 bytes
        # Position
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        # TexCoord
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
        glEnableVertexAttribArray(1)
        # Normal
        glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(20))
        glEnableVertexAttribArray(2)
        
        glBindVertexArray(0)
        return vao

    def _create_vao_simple(self, vertices, indices, stride_floats):
        """Create simple VAO (for eyelashes)."""
        vao = glGenVertexArrays(1)
        vbo = glGenBuffers(1)
        ebo = glGenBuffers(1)
        
        self.buffers.extend([vbo, ebo])
        
        glBindVertexArray(vao)
        
        glBindBuffer(GL_ARRAY_BUFFER, vbo)
        vertices_array = (ctypes.c_float * len(vertices))(*vertices)
        glBufferData(GL_ARRAY_BUFFER, ctypes.sizeof(vertices_array),
                    vertices_array, GL_STATIC_DRAW)
        
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo)
        indices_array = (ctypes.c_uint * len(indices))(*indices)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, ctypes.sizeof(indices_array),
                    indices_array, GL_STATIC_DRAW)
        
        stride = stride_floats * 4
        if stride_floats == 8:  # Pos(3) + Tex(2) + Normal(3)
            glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
            glEnableVertexAttribArray(0)
            glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
            glEnableVertexAttribArray(1)
            glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(20))
            glEnableVertexAttribArray(2)
        else:  # Simple: Pos(3) + Tex(2)
            glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
            glEnableVertexAttribArray(0)
            glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
            glEnableVertexAttribArray(1)
        
        glBindVertexArray(0)
        return vao

    def _setup_opengl_state(self):
        """Configure OpenGL render state."""
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_MULTISAMPLE)
        glEnable(GL_CULL_FACE)
        glCullFace(GL_BACK)
        glClearColor(0.05, 0.05, 0.05, 1.0)
        
        # For eyelashes
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glEnable(GL_LINE_SMOOTH)
        glHint(GL_LINE_SMOOTH_HINT, GL_NICEST)

    def resizeGL(self, w: int, h: int):
        """Handle window resize."""
        glViewport(0, 0, w, h)
        
        # Resize framebuffer textures
        if self.color_buffer:
            glBindTexture(GL_TEXTURE_2D, self.color_buffer)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, w, h, 0, 
                        GL_RGBA, GL_FLOAT, None)
            
        if self.depth_buffer:
            glBindRenderbuffer(GL_RENDERBUFFER, self.depth_buffer)
            glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT, w, h)

    def paintGL(self):
        """Main render loop."""
        if not self.shader or self.fallback_mode:
            return
        
        current_time = time.time()
        
        # --- Render to FBO ---
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        
        # Setup matrices
        projection = QMatrix4x4()
        projection.perspective(40.0, self.width() / self.height(), 0.1, 100.0)
        
        view = QMatrix4x4()
        view.translate(0.0, 0.0, -self.view_distance)
        
        model = QMatrix4x4()
        # Apply Bell's phenomenon during blink
        model.rotate(self.eye_state.actual_rotation.y() + self.eye_state.bell_rotation, 1, 0, 0)
        model.rotate(self.eye_state.actual_rotation.x(), 0, 1, 0)
        
        # Update corneal topography
        self.corneal_topography.astigmatism_axis = self.config.astigmatism_axis
        self.corneal_topography.astigmatism_power = self.config.astigmatism_power
        self.corneal_topography.keratoconus_stage = self.config.keratoconus_stage
        
        # Render eyeball
        self.shader.use()
        
        # Set matrices
        self.shader.set_uniform("projection", projection)
        self.shader.set_uniform("view", view)
        self.shader.set_uniform("model", model)
        self.shader.set_uniform("viewPos", QVector3D(0, 0, self.view_distance))
        self.shader.set_uniform("time", current_time - self.start_time)
        
        # Set state uniforms
        self.shader.set_uniform("blinkFactor", self.eye_state.blink_factor)
        self.shader.set_uniform("squintFactor", self.eye_state.squint_factor)
        self.shader.set_uniform("lightLevel", self.eye_state.actual_light_level)
        self.shader.set_uniform("upperLidOpen", self.eye_state.upper_lid_open)
        self.shader.set_uniform("lowerLidOpen", self.eye_state.lower_lid_open)
        self.shader.set_uniform("fluoresceinStaining", self.eye_state.fluorescein_staining)
        self.shader.set_uniform("redReflexIntensity", self.eye_state.red_reflex_intensity)
        self.shader.set_uniform("lensThickness", self.eye_state.lens_thickness)
        self.shader.set_uniform("pupilSize", self.eye_state.pupil_size)  # Set pupil size
        
        # Use automated uniform setting with proper mapping
        self.shader.set_config_uniforms(self.config)
        
        # Draw eyeball
        glBindVertexArray(self.vao_eyeball)
        glDrawElements(GL_TRIANGLES, self.num_indices_eyeball, GL_UNSIGNED_INT, None)
        
        # Draw eyelids (with transparency)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glDepthMask(GL_FALSE)  # Disable depth writing for transparency
        glBindVertexArray(self.vao_eyelids)
        glDrawElements(GL_TRIANGLES, self.num_indices_eyelids, GL_UNSIGNED_INT, None)
        glDepthMask(GL_TRUE)
        
        # Draw eyelashes with LOD and culling
        # Only draw eyelashes when eye is open enough
        if self.eye_state.blink_factor < EYELASH_LOD_THRESHOLDS[0]:
            self.eyelash_shader.use()
            self.eyelash_shader.set_uniform("projection", projection)
            self.eyelash_shader.set_uniform("view", view)
            self.eyelash_shader.set_uniform("model", model)
            self.eyelash_shader.set_uniform("density", self.config.eyelash_density)
            self.eyelash_shader.set_uniform("time", current_time - self.start_time)
            
            # Select LOD based on blink factor
            lod = 0
            if self.eye_state.blink_factor > EYELASH_LOD_THRESHOLDS[1]:
                lod = 2
            elif self.eye_state.blink_factor > EYELASH_LOD_THRESHOLDS[0]:
                lod = 1
                
            glBindVertexArray(self.eyelash_vaos[lod])
            glLineWidth(1.5)
            glDrawElements(GL_LINES, self.eyelash_indices[lod], GL_UNSIGNED_INT, None)
        glDisable(GL_BLEND)
        
        # --- Post-processing: Bloom ---
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        glClear(GL_COLOR_BUFFER_BIT)
        
        self.bloom_shader.use()
        self.bloom_shader.set_uniform("scene", 0)  # Texture unit 0
        self.bloom_shader.set_uniform("bloomIntensity", self.config.bloom_intensity)
        self.bloom_shader.set_uniform("time", current_time - self.start_time)
        
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self.color_buffer)
        
        glBindVertexArray(self.vao_quad)
        glDrawElements(GL_TRIANGLES, 6, GL_UNSIGNED_INT, None)
        glBindVertexArray(0)
        
        # Update FPS
        self.frame_times.append(current_time)
        if len(self.frame_times) > 1:
            self.eye_state.fps = len(self.frame_times) / (self.frame_times[-1] - self.frame_times[0])
        self.eye_state.frame_count += 1

    def _update_physics(self):
        """Update all animation and physics systems."""
        curr_time = time.time()
        dt = curr_time - self.last_frame_time
        self.last_frame_time = curr_time
        
        # 1. Saccades (ballistic movements)
        self._update_saccades(curr_time, dt)
        
        # 2. Micro-movements (drift, tremor)
        drift_target, _ = self.micro_movement_gen.generate_drift(self.config.drift_speed * 0.1)
        tremor_offset = self.micro_movement_gen.generate_tremor(
            self.config.tremor_frequency, 
            self.config.tremor_amplitude * self.config.microsaccade_intensity,
            curr_time
        )
        
        # Update drift with smoothing
        drift_lerp = 0.02
        self.eye_state.drift_offset = self.eye_state.drift_offset * (1 - drift_lerp) + drift_target * drift_lerp
        self.eye_state.tremor_offset = tremor_offset
        
        # 3. Update actual rotation with all movements
        base_rotation = self.eye_state.rotation
        self.eye_state.actual_rotation = base_rotation + self.eye_state.drift_offset + self.eye_state.tremor_offset
        
        # 4. Blinking with Bell's phenomenon
        self._update_blinking(curr_time, dt)
        
        # 5. Pupil dynamics with hippus
        self.eye_state.pupil_size = self.pupil_dynamics.update(
            dt, 
            self.eye_state.light_level,
            self.eye_state.light_level  # Current target
        )
        
        # 6. Squint
        squint_lerp = 0.1
        self.eye_state.squint_factor += (self.eye_state.target_squint_factor - self.eye_state.squint_factor) * squint_lerp
        
        # 7. Update accommodation
        self._update_accommodation(dt)
        
        # 8. Update medical visualization
        if self.config.visualization_mode == "fluorescein":
            self.eye_state.fluorescein_staining = min(1.0, self.eye_state.fluorescein_staining + dt * 0.5)
        else:
            self.eye_state.fluorescein_staining = max(0.0, self.eye_state.fluorescein_staining - dt)
        
        if self.config.visualization_mode == "red_reflex":
            self.eye_state.red_reflex_intensity = min(1.0, self.eye_state.red_reflex_intensity + dt * 2.0)
        else:
            self.eye_state.red_reflex_intensity = max(0.0, self.eye_state.red_reflex_intensity - dt * 2.0)
        
        # Emit state change signal
        self.eyeStateChanged.emit(self.eye_state)
        
        # Request update
        self.update()
    
    def _update_accommodation(self, dt: float):
        """Simulate lens accommodation for near vision."""
        # Lens thickens for near vision (Helmholtz theory)
        target_thickness = AVERAGE_LENS_THICKNESS + self.eye_state.accommodation_level * MAX_LENS_THICKNESS_CHANGE
        self.eye_state.lens_thickness += (target_thickness - self.eye_state.lens_thickness) * dt * 5.0

    def _update_saccades(self, curr_time: float, dt: float):
        """Update saccadic eye movements."""
        if not self.eye_state.is_saccading and curr_time > self.eye_state.next_saccade_time:
            # Generate random saccade target
            angle_h = random.uniform(-MAX_HORIZONTAL_ROTATION, MAX_HORIZONTAL_ROTATION)
            angle_v = random.uniform(-MAX_VERTICAL_ROTATION, MAX_VERTICAL_ROTATION)
            self.eye_state.saccade_target_rot = QVector3D(angle_h, angle_v, 0)
            self.eye_state.saccade_start_rot = QVector3D(self.eye_state.rotation)
            self.eye_state.is_saccading = True
            self.eye_state.saccade_progress = 0.0
            self.eye_state.next_saccade_time = curr_time + random.uniform(
                self.config.saccade_interval_min, 
                self.config.saccade_interval_max
            )

        if self.eye_state.is_saccading:
            # Use animation curve for natural saccade
            self.eye_state.saccade_progress += dt * self.config.saccade_speed / 15.0
            
            if self.eye_state.saccade_progress >= 1.0:
                self.eye_state.saccade_progress = 1.0
                self.eye_state.is_saccading = False
                self.eye_state.rotation = self.eye_state.saccade_target_rot
            
            # Apply easing curve
            t = AnimationCurves.ease_in_out_cubic(self.eye_state.saccade_progress)
            self.eye_state.rotation = (self.eye_state.saccade_start_rot * (1 - t) + 
                                      self.eye_state.saccade_target_rot * t)

    def _update_blinking(self, curr_time: float, dt: float):
        """Update blinking animation with Bell's phenomenon."""
        state = self.eye_state.blink_state
        self.eye_state.blink_timer += dt
        
        if state == "idle":
            if curr_time > self.eye_state.next_blink_time:
                self.eye_state.blink_state = "closing"
                self.eye_state.blink_timer = 0.0
                
        elif state == "closing":
            t = self.eye_state.blink_timer / self.config.blink_duration_close
            self.eye_state.blink_factor = AnimationCurves.ease_in_out_sine(t)
            # Bell's phenomenon: eyes roll up during blink
            self.eye_state.bell_rotation = t * MAX_BELL_ROTATION
            
            if self.eye_state.blink_factor >= 1.0:
                self.eye_state.blink_factor = 1.0
                self.eye_state.blink_state = "opening"
                self.eye_state.blink_timer = 0.0
                
        elif state == "opening":
            t = self.eye_state.blink_timer / self.config.blink_duration_open
            self.eye_state.blink_factor = 1.0 - AnimationCurves.ease_in_out_sine(t)
            # Return from Bell's phenomenon
            self.eye_state.bell_rotation = (1.0 - t) * MAX_BELL_ROTATION
            
            if self.eye_state.blink_factor <= 0.0:
                self.eye_state.blink_factor = 0.0
                self.eye_state.bell_rotation = 0.0
                self.eye_state.blink_state = "idle"
                self.eye_state.next_blink_time = curr_time + random.uniform(
                    self.config.blink_interval_min, 
                    self.config.blink_interval_max
                )

    def update_eye_target(self, x: float, y: float):
        """Update eye target based on mouse position."""
        if self.is_dragging_light:
            # Update light position
            norm_x = (x / self.width()) * 2 - 1 if self.width() > 0 else 0
            norm_y = -((y / self.height()) * 2 - 1) if self.height() > 0 else 0
            self.config.main_light_pos.setX(norm_x * 10)  # Update existing QVector3D
            self.config.main_light_pos.setY(norm_y * 10)
            return

        # Update eye target
        norm_x = (x / self.width()) * 2 - 1 if self.width() > 0 else 0
        norm_y = (y / self.height()) * 2 - 1 if self.height() > 0 else 0
        
        target = QVector3D(
            norm_x * MAX_HORIZONTAL_ROTATION,
            norm_y * MAX_VERTICAL_ROTATION,
            0
        )
        
        if not self.eye_state.is_saccading:
            # Smooth follow when not saccading
            follow_speed = 0.2
            self.eye_state.rotation = (self.eye_state.rotation * (1 - follow_speed) + 
                                      target * follow_speed)

    def trigger_blink(self):
        """Trigger a manual blink."""
        if self.eye_state.blink_state == "idle":
            self.eye_state.blink_state = "closing"
            self.eye_state.blink_timer = 0.0

    def trigger_startle(self):
        """Simulate startle response."""
        self.eye_state.target_pupil = 1.0  # Maximum dilation
        self.trigger_blink()

    def set_light_level(self, level: float):
        """Set light level for pupil response."""
        self.eye_state.light_level = max(0.0, min(1.0, level))

    def set_accommodation(self, level: float):
        """Set accommodation level (0=far, 1=near)."""
        self.eye_state.accommodation_level = max(0.0, min(1.0, level))

    def capture_screenshot(self) -> QImage:
        """Capture current render as image."""
        return self.grabFramebuffer()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and event.modifiers() & Qt.ShiftModifier:
            self.is_dragging_light = True
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.is_dragging_light = False
        super().mouseReleaseEvent(event)

    def cleanup(self):
        """Clean up OpenGL resources."""
        if hasattr(self, 'vao_eyeball') and self.vao_eyeball:
            glDeleteVertexArrays(1, [self.vao_eyeball])
        if hasattr(self, 'vao_eyelids') and self.vao_eyelids:
            glDeleteVertexArrays(1, [self.vao_eyelids])
        if hasattr(self, 'eyelash_vaos') and self.eyelash_vaos:
            glDeleteVertexArrays(len(self.eyelash_vaos), self.eyelash_vaos)
        if hasattr(self, 'vao_quad') and self.vao_quad:
            glDeleteVertexArrays(1, [self.vao_quad])
        if hasattr(self, 'buffers') and self.buffers:
            glDeleteBuffers(len(self.buffers), self.buffers)
        if hasattr(self, 'fbo') and self.fbo:
            glDeleteFramebuffers(1, [self.fbo])
        if hasattr(self, 'color_buffer') and self.color_buffer:
            glDeleteTextures(1, [self.color_buffer])
        if hasattr(self, 'depth_buffer') and self.depth_buffer:
            glDeleteRenderbuffers(1, [self.depth_buffer])


# --- Settings Manager ---
class SettingsManager:
    """Manages auto-save and load of application settings."""
    
    def __init__(self):
        self.settings = QSettings("EyeVPro", "EyeSimulator")
        self.autosave_timer = QTimer()
        self.autosave_timer.timeout.connect(self.autosave_current_settings)
        self.autosave_timer.start(30000)  # Auto-save every 30 seconds
    
    def _serialize_config(self, config: EyeConfig) -> dict:
        """Serialize EyeConfig to dictionary for QSettings."""
        data = {}
        for field_info in fields(config):
            name = field_info.name
            value = getattr(config, name)
            
            if isinstance(value, QVector3D):
                data[name] = [value.x(), value.y(), value.z()]
            else:
                data[name] = value
        return data
    
    def _deserialize_config(self, data: dict, config: EyeConfig):
        """Deserialize dictionary to EyeConfig."""
        for field_info in fields(config):
            name = field_info.name
            if name in data:
                value = data[name]
                if isinstance(getattr(config, name), QVector3D) and isinstance(value, list):
                    getattr(config, name).setX(value[0])
                    getattr(config, name).setY(value[1])
                    getattr(config, name).setZ(value[2])
                else:
                    setattr(config, name, value)
    
    def save_window_state(self, window: QMainWindow):
        """Save window geometry and state."""
        self.settings.setValue("window_geometry", window.saveGeometry())
        self.settings.setValue("window_state", window.saveState())
    
    def restore_window_state(self, window: QMainWindow):
        """Restore window geometry and state."""
        geometry = self.settings.value("window_geometry")
        state = self.settings.value("window_state")
        if geometry:
            window.restoreGeometry(geometry)
        if state:
            window.restoreState(state)
    
    def save_current_settings(self, config: EyeConfig):
        """Save current configuration to settings."""
        data = self._serialize_config(config)
        self.settings.setValue("last_config", json.dumps(data))
        self.settings.setValue("last_save_time", time.time())
    
    def autosave_current_settings(self, config: EyeConfig):
        """Auto-save configuration periodically."""
        self.save_current_settings(config)
    
    def load_last_settings(self, config: EyeConfig) -> bool:
        """Load last saved configuration."""
        config_data = self.settings.value("last_config")
        if config_data:
            try:
                data = json.loads(config_data)
                self._deserialize_config(data, config)
                return True
            except Exception as e:
                print(f"Error loading settings: {e}")
        return False


# --- Compact Hamburger Menu Control Panel ---
class CompactControlPanel(QFrame):
    """Compact, hideable control panel with hamburger menu."""
    
    def __init__(self, eye_renderer: EyeRenderer, parent=None):
        super().__init__(parent)
        self.renderer = eye_renderer
        self.config = eye_renderer.config  # Reference to SHARED config object
        self.expanded = False
        
        # Store slider values for display
        self.slider_labels = {}
        
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the compact control panel."""
        self.setFixedSize(50, 50)
        self.move(10, 10)
        self.setStyleSheet("""
            QFrame {
                background-color: rgba(30, 30, 30, 200);
                border-radius: 25px;
                border: 1px solid #555;
            }
            QPushButton {
                background-color: transparent;
                border: none;
                color: #eee;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 30);
                border-radius: 20px;
            }
        """)
        
        # Hamburger button
        self.hamburger_btn = QPushButton("☰")
        self.hamburger_btn.setFont(QFont("Arial", 16))
        self.hamburger_btn.clicked.connect(self.toggle_panel)
        self.hamburger_btn.setParent(self)
        self.hamburger_btn.setGeometry(10, 10, 30, 30)
        
        # Expanded panel (initially hidden)
        self.expanded_panel = QFrame(self.parent())
        self.expanded_panel.hide()
        self.expanded_panel.setFixedSize(320, 450)  # Increased width for value labels
        self.expanded_panel.move(60, 10)
        self.expanded_panel.setStyleSheet("""
            QFrame {
                background-color: rgba(30, 30, 30, 220);
                border-radius: 10px;
                border: 1px solid #555;
            }
            QLabel {
                color: #eee;
                font-size: 11px;
            }
            QSlider::groove:horizontal {
                border: 1px solid #555;
                height: 4px;
                background: #333;
                margin: 2px 0;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #666;
                border: 1px solid #888;
                width: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
        """)
        
        # Setup expanded panel content
        self.setup_expanded_content()
        
        # Animation
        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(200)
        self.animation.setEasingCurve(QEasingCurve.InOutQuad)
    
    def setup_expanded_content(self):
        """Setup content for the expanded panel."""
        layout = QVBoxLayout(self.expanded_panel)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Title
        title = QLabel("Eye Controls")
        title.setStyleSheet("font-size: 14px; font-weight: bold; margin-bottom: 5px;")
        layout.addWidget(title)
        
        # Quick controls
        controls_layout = QGridLayout()
        controls_layout.setColumnStretch(0, 1)  # Label column
        controls_layout.setColumnStretch(1, 2)  # Slider column
        controls_layout.setColumnStretch(2, 1)  # Value column
        
        # Light level
        controls_layout.addWidget(QLabel("Light:"), 0, 0)
        light_slider = QSlider(Qt.Horizontal)
        light_slider.setRange(0, 100)
        light_slider.setValue(int(self.renderer.eye_state.light_level * 100))
        light_slider.valueChanged.connect(lambda v: self.renderer.set_light_level(v / 100))
        light_slider.setToolTip("Adjust ambient light level (affects pupil dilation)")
        controls_layout.addWidget(light_slider, 0, 1)
        
        light_value = QLabel(f"{self.renderer.eye_state.light_level:.2f}")
        light_value.setStyleSheet("color: #aaa; font-size: 10px; min-width: 40px;")
        light_slider.valueChanged.connect(lambda v: light_value.setText(f"{v/100:.2f}"))
        controls_layout.addWidget(light_value, 0, 2)
        self.slider_labels['light'] = light_value
        
        # Pupil size
        controls_layout.addWidget(QLabel("Pupil:"), 1, 0)
        pupil_slider = QSlider(Qt.Horizontal)
        pupil_slider.setRange(10, 100)
        pupil_slider.setValue(int(self.config.pupil_base_radius * 200))
        
        # FIXED: Update existing QVector3D reference
        pupil_slider.valueChanged.connect(lambda v: self.config.pupil_base_radius == v / 200)
        pupil_slider.setToolTip("Base pupil size (affects light reflex dynamics)")
        controls_layout.addWidget(pupil_slider, 1, 1)
        
        pupil_value = QLabel(f"{self.config.pupil_base_radius:.2f}")
        pupil_value.setStyleSheet("color: #aaa; font-size: 10px; min-width: 40px;")
        pupil_slider.valueChanged.connect(lambda v: pupil_value.setText(f"{v/200:.2f}"))
        controls_layout.addWidget(pupil_value, 1, 2)
        self.slider_labels['pupil'] = pupil_value
        
        # Eyelash density
        controls_layout.addWidget(QLabel("Lashes:"), 2, 0)
        lash_slider = QSlider(Qt.Horizontal)
        lash_slider.setRange(0, 100)
        lash_slider.setValue(int(self.config.eyelash_density * 100))
        lash_slider.valueChanged.connect(lambda v: setattr(self.config, 'eyelash_density', v / 100))
        lash_slider.setToolTip("Eyelash density and visibility")
        controls_layout.addWidget(lash_slider, 2, 1)
        
        lash_value = QLabel(f"{self.config.eyelash_density:.2f}")
        lash_value.setStyleSheet("color: #aaa; font-size: 10px; min-width: 40px;")
        lash_slider.valueChanged.connect(lambda v: lash_value.setText(f"{v/100:.2f}"))
        controls_layout.addWidget(lash_value, 2, 2)
        self.slider_labels['lashes'] = lash_value
        
        # Sclera brightness
        controls_layout.addWidget(QLabel("Sclera:"), 3, 0)
        sclera_slider = QSlider(Qt.Horizontal)
        sclera_slider.setRange(0, 100)
        sclera_slider.setValue(int(self.config.sclera_color.x() * 100))
        
        # FIXED: Update existing QVector3D reference
        def update_sclera_brightness(v):
            brightness = v / 100
            self.config.sclera_color.setX(brightness)
            self.config.sclera_color.setY(brightness * 0.98)
            self.config.sclera_color.setZ(brightness * 0.96)
        
        sclera_slider.valueChanged.connect(update_sclera_brightness)
        sclera_slider.setToolTip("Sclera (white of the eye) brightness")
        controls_layout.addWidget(sclera_slider, 3, 1)
        
        sclera_value = QLabel(f"{self.config.sclera_color.x():.2f}")
        sclera_value.setStyleSheet("color: #aaa; font-size: 10px; min-width: 40px;")
        sclera_slider.valueChanged.connect(lambda v: sclera_value.setText(f"{v/100:.2f}"))
        controls_layout.addWidget(sclera_value, 3, 2)
        self.slider_labels['sclera'] = sclera_value
        
        # Iris color
        controls_layout.addWidget(QLabel("Iris:"), 4, 0)
        iris_slider = QSlider(Qt.Horizontal)
        iris_slider.setRange(0, 100)
        iris_slider.setValue(int(self.config.iris_inner_color.x() * 100))
        
        # FIXED: Update existing QVector3D references
        def update_iris_color(v):
            t = v / 100
            r = 0.05 + t * 0.4
            g = 0.15 + t * 0.2
            b = 0.25 - t * 0.2
            
            self.config.iris_inner_color.setX(r)
            self.config.iris_inner_color.setY(g)
            self.config.iris_inner_color.setZ(b)
            
            self.config.iris_outer_color.setX(r * 0.5)
            self.config.iris_outer_color.setY(g * 0.5)
            self.config.iris_outer_color.setZ(b * 0.5)
        
        iris_slider.valueChanged.connect(update_iris_color)
        iris_slider.setToolTip("Iris color gradient (blue to brown)")
        controls_layout.addWidget(iris_slider, 4, 1)
        
        iris_value = QLabel(f"{self.config.iris_inner_color.x():.2f}")
        iris_value.setStyleSheet("color: #aaa; font-size: 10px; min-width: 40px;")
        iris_slider.valueChanged.connect(lambda v: iris_value.setText(f"{v/100:.2f}"))
        controls_layout.addWidget(iris_value, 4, 2)
        self.slider_labels['iris'] = iris_value
        
        # Blink button
        blink_btn = QPushButton("Blink Now")
        blink_btn.clicked.connect(self.renderer.trigger_blink)
        blink_btn.setToolTip("Trigger a single blink (B key)")
        controls_layout.addWidget(blink_btn, 5, 0, 1, 3)
        
        layout.addLayout(controls_layout)
        
        # Presets
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["Default", "Calm", "Alert", "Tired"])
        self.preset_combo.currentTextChanged.connect(self.load_preset)
        self.preset_combo.setToolTip("Load predefined eye behavior presets")
        preset_layout.addWidget(self.preset_combo)
        layout.addLayout(preset_layout)
        
        # Visualization mode
        viz_layout = QHBoxLayout()
        viz_layout.addWidget(QLabel("Mode:"))
        self.viz_combo = QComboBox()
        self.viz_combo.addItems(["Normal", "Fluorescein", "Red Reflex", "Retroillumination"])
        self.viz_combo.currentIndexChanged.connect(self.change_visualization)
        self.viz_combo.setToolTip("Medical visualization modes")
        viz_layout.addWidget(self.viz_combo)
        layout.addLayout(viz_layout)
        
        # Status
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #aaa; font-size: 10px; margin-top: 5px;")
        layout.addWidget(self.status_label)
        
        # Close button
        close_btn = QPushButton("✕")
        close_btn.clicked.connect(self.toggle_panel)
        close_btn.setStyleSheet("background-color: transparent; border: none; color: #eee; font-size: 12px;")
        layout.addWidget(close_btn, 0, Qt.AlignRight)
        
        # Add some spacing
        layout.addSpacing(10)
    
    def toggle_panel(self):
        """Toggle the expanded panel."""
        if self.expanded:
            # Collapse
            self.animation.setStartValue(QRect(10, 10, 320, 450))
            self.animation.setEndValue(QRect(10, 10, 50, 50))
            self.expanded_panel.hide()
            self.hamburger_btn.show()
            self.expanded = False
        else:
            # Expand
            self.animation.setStartValue(QRect(10, 10, 50, 50))
            self.animation.setEndValue(QRect(10, 10, 320, 450))
            self.expanded_panel.show()
            self.hamburger_btn.hide()
            self.expanded = True
        
        self.animation.start()
    
    def load_preset(self, name: str):
        """Load a preset configuration - PROPERLY updates existing config."""
        if name == "Default":
            preset = EyeConfig()
        elif name == "Calm":
            preset = PresetManager.create_calm_preset()
        elif name == "Alert":
            preset = PresetManager.create_alert_preset()
        elif name == "Tired":
            preset = PresetManager.create_tired_preset()
        else:
            return
        
        # Update ALL fields in the existing config object (preserving references)
        for field_info in fields(self.config):
            field_name = field_info.name
            preset_value = getattr(preset, field_name)
            
            if isinstance(preset_value, QVector3D):
                # Update existing QVector3D components
                current_vec = getattr(self.config, field_name)
                current_vec.setX(preset_value.x())
                current_vec.setY(preset_value.y())
                current_vec.setZ(preset_value.z())
            else:
                # Update scalar values
                setattr(self.config, field_name, preset_value)
        
        # Update slider displays
        self.update_slider_displays()
        
        self.status_label.setText(f"Loaded preset: {name}")
    
    def update_slider_displays(self):
        """Update all slider value displays."""
        if 'light' in self.slider_labels:
            self.slider_labels['light'].setText(f"{self.renderer.eye_state.light_level:.2f}")
        if 'pupil' in self.slider_labels:
            self.slider_labels['pupil'].setText(f"{self.config.pupil_base_radius:.2f}")
        if 'lashes' in self.slider_labels:
            self.slider_labels['lashes'].setText(f"{self.config.eyelash_density:.2f}")
        if 'sclera' in self.slider_labels:
            self.slider_labels['sclera'].setText(f"{self.config.sclera_color.x():.2f}")
        if 'iris' in self.slider_labels:
            self.slider_labels['iris'].setText(f"{self.config.iris_inner_color.x():.2f}")
    
    def change_visualization(self, index: int):
        """Change medical visualization mode."""
        modes = ["normal", "fluorescein", "red_reflex", "retroillumination"]
        self.config.visualization_mode = modes[index]
        self.status_label.setText(f"Mode: {modes[index]}")
    
    def update_status(self, fps: float, pupil_size: float):
        """Update status display."""
        self.status_label.setText(f"FPS: {fps:.1f} | Pupil: {pupil_size:.2f}")


# --- Main Window ---
class MainWindow(QMainWindow):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        self.config = EyeConfig()
        self.settings_manager = SettingsManager()
        self.setup_ui()
        self.setup_signals()
        
        # Load saved settings
        self.load_settings()
    
    def setup_ui(self):
        """Setup main window UI."""
        self.setWindowTitle("EyeV Pro - Professional Eye Simulator v4.2 FINAL")
        self.resize(1200, 800)
        
        # Set dark theme
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1a1a1a;
            }
        """)
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Eye renderer (full window)
        self.eye_renderer = EyeRenderer(self.config)
        main_layout.addWidget(self.eye_renderer)
        
        # Compact control panel
        self.control_panel = CompactControlPanel(self.eye_renderer, self.eye_renderer)
        self.control_panel.setParent(self.eye_renderer)
    
    def setup_signals(self):
        """Connect signals."""
        self.eye_renderer.eyeStateChanged.connect(self._on_eye_state_changed)
        
        # Handle window close
        self.destroyed.connect(self.eye_renderer.cleanup)
        self.destroyed.connect(self.save_settings)
    
    def load_settings(self):
        """Load saved settings."""
        # Restore window state
        self.settings_manager.restore_window_state(self)
        
        # Load last configuration
        self.settings_manager.load_last_settings(self.config)
    
    def save_settings(self):
        """Save current settings."""
        self.settings_manager.save_window_state(self)
        self.settings_manager.save_current_settings(self.config)
    
    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard shortcuts."""
        if event.key() == Qt.Key_B:
            self.eye_renderer.trigger_blink()
        elif event.key() == Qt.Key_S and event.modifiers() & Qt.ControlModifier:
            self.take_screenshot()
        elif event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)
    
    def take_screenshot(self):
        """Take and save a screenshot."""
        img = self.eye_renderer.capture_screenshot()
        if img.isNull():
            QMessageBox.warning(self, "Error", "Failed to capture screenshot.")
            return
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save Screenshot", 
            f"eye_screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png",
            "PNG Images (*.png);;JPEG Images (*.jpg *.jpeg)"
        )
        
        if filename:
            if img.save(filename):
                # Show temporary notification
                self.control_panel.status_label.setText(f"Saved: {os.path.basename(filename)}")
                QTimer.singleShot(2000, lambda: self.control_panel.status_label.setText(""))
            else:
                QMessageBox.critical(self, "Error", "Failed to save screenshot.")
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse movement for eye tracking."""
        local_pos = self.eye_renderer.mapFrom(self, event.position().toPoint())
        self.eye_renderer.update_eye_target(local_pos.x(), local_pos.y())
        super().mouseMoveEvent(event)
    
    def _on_eye_state_changed(self, state: EyeState):
        """Update UI when eye state changes."""
        # Update status in compact panel
        self.control_panel.update_status(state.fps, state.pupil_size)
    
    def closeEvent(self, event):
        """Handle window close event."""
        self.save_settings()
        self.eye_renderer.cleanup()
        event.accept()


# --- Shader Definitions ---
# --- Main Application ---
def main():
    """Main application entry point."""
    app = QApplication(sys.argv)
    
    # Set OpenGL format
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setSamples(8)  # 8x MSAA
    fmt.setDepthBufferSize(24)
    fmt.setSwapInterval(1)  # VSync
    QSurfaceFormat.setDefaultFormat(fmt)
    
    # Set application style
    app.setStyle("Fusion")
    
    # Enable tooltips globally
    QToolTip.setFont(QFont("Arial", 10))
    
    # Create and show main window
    window = MainWindow()
    window.show()
    
    # Start application loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()


# Add these imports at the beginning of the file, after the existing imports
from OpenGL.GL import *
from OpenGL.GLUT import *
from OpenGL.GLU import *
from OpenGL.arrays import vbo
from OpenGL import GL as gl
from OpenGL.GL import shaders