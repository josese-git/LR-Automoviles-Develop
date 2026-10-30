/**
 * Admin.js - Advanced Logic (Drag&Drop, Menus, Edit, Files)
 */
import store from './store.js';
import { storage, ref, uploadBytes, getDownloadURL } from './firebase-config.js';

let activeMenuId = null;
let isSortMode = false;
let draggedItem = null;
// Local cache of cars for drag & drop and editing
let currentCars = [];

document.addEventListener('DOMContentLoaded', () => {
    if (window.auth && !window.auth.isAuthenticated()) {
        window.location.href = 'login.html';
        return;
    }

    // Subscribe to store updates
    store.subscribe((cars) => {
        currentCars = cars;
        renderAdminInventory(cars);
    });

    setupDropZones();

    // Close menus when clicking outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.menu-trigger') && !e.target.closest('.card-menu')) {
            closeAllMenus();
        }
    });
});

// --- RENDER LOGIC ---
function renderAdminInventory(cars) {
    const list = document.getElementById('inventory-list');
    list.innerHTML = '';

    if (cars.length === 0) {
        list.innerHTML = '<p style="color:white;">Esperando datos...</p>';
        return;
    }

    cars.forEach(car => {
        const item = document.createElement('div');
        item.className = 'admin-card';
        // Add drag attributes
        item.setAttribute('draggable', isSortMode);
        item.dataset.id = car.id;
        if (isSortMode) item.classList.add('sortable');

        // Status Badge
        const statusBadge = car.sold
            ? '<span class="status-badge sold">VENDIDO</span>'
            : '<span class="status-badge">EN VENTA</span>';

        item.innerHTML = `
            <img src="${car.image}" alt="Car">
            <div class="admin-card-info">
                <h4>${car.brand} ${car.model}</h4>
                <p>${car.year} • ${car.price}</p>
                ${statusBadge}
            </div>
            
            <!-- Overflow Menu -->
            <div class="menu-trigger" onclick="toggleMenu('${car.id}', event)">⋮</div>
            <div class="card-menu" id="menu-${car.id}">
                <div class="card-menu-item" onclick="editCar('${car.id}')">✏️ Editar</div>
                <div class="card-menu-item" onclick="toggleSortMode()">⇵ Ordenar</div>
                <div class="card-menu-item delete" onclick="deleteCar('${car.id}')">🗑 Eliminar</div>
            </div>
        `;

        // Drag Events
        item.addEventListener('dragstart', handleDragStart);
        item.addEventListener('dragover', handleDragOver);
        item.addEventListener('drop', handleDrop);
        item.addEventListener('dragend', handleDragEnd);

        list.appendChild(item);
    });
}

// --- MENU LOGIC ---
window.toggleMenu = function (id, event) {
    event.stopPropagation();
    const menu = document.getElementById(`menu-${id}`);
    const isVisible = menu.classList.contains('visible');
    closeAllMenus();
    if (!isVisible) {
        menu.classList.add('visible');
    }
};

function closeAllMenus() {
    document.querySelectorAll('.card-menu').forEach(m => m.classList.remove('visible'));
}

// --- MODAL & FORM LOGIC ---
window.openModal = function (mode = 'create', carId = null) {
    document.getElementById('carModal').style.display = 'flex';
    document.getElementById('carForm').reset();
    resetDropZones();

    if (mode === 'edit' && carId) {
        document.getElementById('modalTitle').innerText = 'Editar Vehículo';
        document.getElementById('editCarId').value = carId;

        // Populate Data from local cache
        const car = currentCars.find(c => c.id === carId);
        if (car) {
            const form = document.getElementById('carForm');
            form.brand.value = car.brand;
            form.model.value = car.model;
            form.year.value = car.year;
            form.price.value = car.price;
            form.km.value = car.km || '';
            form.fuel.value = car.fuel;
            form.transmission.value = car.transmission;
            form.cv.value = car.cv || '';
            form.description.value = car.description || '';
            form.sold.value = car.sold.toString();
            form.logoSize.value = car.logoSize || 100;
            form.logoMargin.value = car.logoMargin || '';

            // Populate Images (Hidden Inputs + Previews)
            if (car.image) updatePreviewFromUrl(car.image, 'mainPreview', 'finalImageSrc');
            if (car.logo) updatePreviewFromUrl(car.logo, 'logoPreview', 'finalLogoSrc');

            // Populate Exterior Gallery (5 slots)
            exteriorFiles = car.galleryExterior || [null, null, null, null, null];
            while (exteriorFiles.length < 5) exteriorFiles.push(null);
            renderExteriorGallery();

            // Populate Interior Gallery
            interiorFiles = car.galleryInterior || [];
            renderInteriorGallery();
        }
    } else {
        document.getElementById('modalTitle').innerText = 'Nuevo Vehículo';
        document.getElementById('editCarId').value = '';
        exteriorFiles = [null, null, null, null, null];
        interiorFiles = [];
        renderExteriorGallery();
        renderInteriorGallery();
    }
};

window.closeModal = function () {
    document.getElementById('carModal').style.display = 'none';
};

// Helper to convert Base64 to Blob
function dataURItoBlob(dataURI) {
    // Check if it's already a URL (http/https), if so return null (no upload needed)
    if (!dataURI || typeof dataURI !== 'string') return null;
    if (dataURI.startsWith('http') || dataURI.startsWith('gs://') || dataURI.startsWith('/')) return null;

    // Strict check for Data URI format
    if (!dataURI.startsWith('data:')) {
        console.warn("dataURItoBlob: String is not a Data URI nor valid URL:", dataURI.substring(0, 50));
        return null; // Treat as text/URL
    }

    try {
        const split = dataURI.split(',');
        if (split.length < 2) return null;

        const byteString = atob(split[1]);
        const mimeString = split[0].split(':')[1].split(';')[0];
        const ab = new ArrayBuffer(byteString.length);
        const ia = new Uint8Array(ab);
        for (let i = 0; i < byteString.length; i++) {
            ia[i] = byteString.charCodeAt(i);
        }
        return new Blob([ab], { type: mimeString });
    } catch (e) {
        console.error("Error converting Data URI to Blob:", e);
        return null;
    }
}

// Helper to upload file to Storage
async function uploadImageToStorage(blob, brand, model, type, index = 0) {
    if (!blob) return null;
    const timestamp = Date.now();
    // Folder structure: anuncios/Kia/Sportage/timestamp_type.png
    // Sanitize brand/model
    const safeBrand = brand.replace(/\s+/g, '_');
    const safeModel = model.replace(/\s+/g, '_');

    // Construct Path
    // Type can be 'main', 'logo', 'gallery_0', 'gallery_1'...
    const filename = `${timestamp}_${type}.png`;
    const storageRef = ref(storage, `anuncios/${safeBrand}/${safeModel}/${filename}`);

    await uploadBytes(storageRef, blob);
    return await getDownloadURL(storageRef);
}

// Global scope
window.submitCarForm = async function () {
    const btn = document.querySelector('button[onclick="submitCarForm()"]');
    const originalText = btn.innerText;
    btn.innerText = "Subiendo imágenes...";
    btn.disabled = true;

    try {
        const form = document.getElementById('carForm');
        const formData = new FormData(form);

        // Validation
        const brand = formData.get('brand');
        const model = formData.get('model');
        if (!brand || !model) throw new Error("Marca y Modelo son obligatorios para subir imágenes.");

        // Get Current Base64 Values
        const mainImageBase64 = document.getElementById('finalImageSrc').value;
        const logoImageBase64 = document.getElementById('finalLogoSrc').value;

        // Process Uploads
        let mainImageUrl = mainImageBase64;
        let logoImageUrl = logoImageBase64;

        // 1. Upload Main Image
        const mainBlob = dataURItoBlob(mainImageBase64);
        if (mainBlob) {
            mainImageUrl = await uploadImageToStorage(mainBlob, brand, model, 'main');
        }

        // 2. Upload Logo
        const logoBlob = dataURItoBlob(logoImageBase64);
        if (logoBlob) {
            logoImageUrl = await uploadImageToStorage(logoBlob, brand, model, 'logo');
        }

        // 3. Upload Exterior Gallery (5 slots)
        const newExteriorUrls = [];
        for (let i = 0; i < exteriorFiles.length; i++) {
            const fileData = exteriorFiles[i];
            if (!fileData) {
                newExteriorUrls.push(null);
                continue;
            }
            const fileBlob = dataURItoBlob(fileData);
            if (fileBlob) {
                const url = await uploadImageToStorage(fileBlob, brand, model, `exterior_${i}`);
                newExteriorUrls.push(url);
            } else {
                newExteriorUrls.push(fileData); // Already a URL
            }
        }

        // 4. Upload Interior Gallery (up to 9)
        const newInteriorUrls = [];
        for (let i = 0; i < interiorFiles.length; i++) {
            const fileData = interiorFiles[i];
            const fileBlob = dataURItoBlob(fileData);
            if (fileBlob) {
                const url = await uploadImageToStorage(fileBlob, brand, model, `interior_${i}`);
                newInteriorUrls.push(url);
            } else {
                newInteriorUrls.push(fileData); // Already a URL
            }
        }

        const carData = {
            brand: brand,
            model: model,
            year: formData.get('year'),
            fuel: formData.get('fuel'),
            transmission: formData.get('transmission'),
            cv: formData.get('cv') || '',
            price: formData.get('price'),
            km: formData.get('km'),
            image: mainImageUrl,
            logo: logoImageUrl,
            logoSize: formData.get('logoSize') || 100,
            logoMargin: formData.get('logoMargin'),
            description: formData.get('description'),
            sold: formData.get('sold') === 'true',
            galleryExterior: newExteriorUrls,
            galleryInterior: newInteriorUrls
        };

        const editId = document.getElementById('editCarId').value;

        // Logic for edit mode... (keeping existing, but images are now URLs)
        if (editId) {
            await store.updateCar(editId, carData);
        } else {
            await store.addCar(carData);
        }

        closeModal();
    } catch (error) {
        console.error("Error saving car:", error);
        alert("Error al guardar: " + error.message);
    } finally {
        btn.innerText = originalText;
        btn.disabled = false;
    }
};

window.deleteCar = async function (id) {
    if (confirm('¿Eliminar vehículo?')) {
        try {
            await store.deleteCar(id);
        } catch (error) {
            console.error("Error deleting car:", error);
            alert("Error al eliminar: " + error.message);
        }
    }
};

window.editCar = function (id) {
    openModal('edit', id);
};

// --- DRAG & DROP SORTING ---
window.toggleSortMode = function () {
    isSortMode = !isSortMode;
    renderAdminInventory(currentCars); // Re-render to add/remove draggable attributes
};

function handleDragStart(e) {
    if (!isSortMode) return;
    draggedItem = this;
    this.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
}

function handleDragOver(e) {
    if (!isSortMode) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
}

function handleDrop(e) {
    if (!isSortMode) return;
    e.preventDefault();
    const targetItem = e.target.closest('.admin-card');

    if (targetItem && targetItem !== draggedItem) {
        const draggedId = draggedItem.dataset.id;
        const targetId = targetItem.dataset.id;

        const fromIndex = currentCars.findIndex(c => c.id === draggedId);
        const toIndex = currentCars.findIndex(c => c.id === targetId);

        if (fromIndex === -1 || toIndex === -1) {
            console.error("Indices not found for", draggedId, targetId);
            return;
        }

        // Modify local cache order
        const [movedCar] = currentCars.splice(fromIndex, 1);
        currentCars.splice(toIndex, 0, movedCar);

        // Optimistic UI Update
        renderAdminInventory(currentCars);

        // Persist to Firestore
        store.reorderCars(currentCars).catch(err => {
            console.error(err);
            alert('Error al guardar el nuevo orden: ' + err.message);
        });
    }
}

function handleDragEnd() {
    if (draggedItem) draggedItem.classList.remove('dragging');
    draggedItem = null;
}


// --- FILE HANDLING & EDITOR ---
let cropper = null;
let activeEditorType = null; // 'main' | 'logo' | 'exterior' | 'interior'
let activeSlotIndex = null; // For exterior gallery slots
let editingInteriorIndex = null; // For interior edit

// Gallery arrays
let exteriorFiles = [null, null, null, null, null]; // 5 slots
let interiorFiles = []; // Up to 9

function setupDropZones() {
    // Main and Logo drop zones (these still use editor)
    ['main', 'logo'].forEach(type => {
        const zone = document.getElementById(`${type}DropZone`);
        const input = document.getElementById(`${type}ImageInput`) || document.getElementById(`${type}Input`);

        if (!zone || !input) return;

        zone.addEventListener('dragover', (e) => {
            e.preventDefault();
            zone.classList.add('dragover');
        });

        zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));

        zone.addEventListener('drop', (e) => {
            e.preventDefault();
            zone.classList.remove('dragover');
            const files = e.dataTransfer.files;
            if (files.length > 0) handleEditorOpen(files[0], type);
        });

        input.addEventListener('change', (e) => {
            if (e.target.files.length > 0) handleEditorOpen(e.target.files[0], type);
        });
    });

    // Setup exterior slots with drag-drop and click
    setupExteriorSlots();

    // Exterior image input (for file picker)
    const exteriorInput = document.getElementById('exteriorImageInput');
    if (exteriorInput) {
        exteriorInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0 && activeSlotIndex !== null) {
                // Direct upload without editor
                readFileAsBase64(e.target.files[0], (base64) => {
                    exteriorFiles[activeSlotIndex] = base64;
                    renderExteriorGallery();
                    activeSlotIndex = null;
                });
            }
            e.target.value = ''; // Reset input
        });
    }

    // Interior drop zone and input - supports multiple files
    const interiorZone = document.getElementById('interiorDropZone');
    const interiorInput = document.getElementById('interiorImageInput');
    if (interiorZone && interiorInput) {
        interiorZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            interiorZone.classList.add('dragover');
        });
        interiorZone.addEventListener('dragleave', () => interiorZone.classList.remove('dragover'));
        interiorZone.addEventListener('drop', (e) => {
            e.preventDefault();
            interiorZone.classList.remove('dragover');
            const files = Array.from(e.dataTransfer.files);
            addMultipleInteriorImages(files);
        });
        interiorInput.addEventListener('change', (e) => {
            const files = Array.from(e.target.files);
            addMultipleInteriorImages(files);
            e.target.value = ''; // Reset input
        });
    }

    // Setup exterior drag-drop for reordering
    setupExteriorDragDrop();
}

// Setup exterior slots to accept dropped files and clicks
function setupExteriorSlots() {
    const slots = document.querySelectorAll('#exteriorGalleryGrid .gallery-slot');

    slots.forEach((slot, index) => {
        // Click to upload
        slot.addEventListener('click', (e) => {
            if (e.target.classList.contains('slot-edit') || e.target.classList.contains('slot-remove')) return;
            triggerExteriorUpload(index);
        });

        // Drag-drop files onto slot
        slot.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.stopPropagation();
            // Only show drop effect if dragging files (not reordering)
            if (e.dataTransfer.types.includes('Files')) {
                slot.classList.add('drag-over');
            }
        });

        slot.addEventListener('dragleave', (e) => {
            e.stopPropagation();
            slot.classList.remove('drag-over');
        });

        slot.addEventListener('drop', (e) => {
            e.stopPropagation();
            slot.classList.remove('drag-over');

            // Check if dropping files (not reordering)
            if (e.dataTransfer.files.length > 0) {
                e.preventDefault();
                const file = e.dataTransfer.files[0];
                if (file.type.startsWith('image/')) {
                    readFileAsBase64(file, (base64) => {
                        exteriorFiles[index] = base64;
                        renderExteriorGallery();
                    });
                }
            }
        });
    });
}

// Add multiple interior images at once
function addMultipleInteriorImages(files) {
    const remaining = 9 - interiorFiles.length;
    if (remaining <= 0) {
        alert('Máximo 9 fotos de interior');
        return;
    }

    const toAdd = files.slice(0, remaining).filter(f => f.type.startsWith('image/'));
    let processed = 0;

    toAdd.forEach(file => {
        readFileAsBase64(file, (base64) => {
            interiorFiles.push(base64);
            processed++;
            if (processed === toAdd.length) {
                renderInteriorGallery();
            }
        });
    });
}

// Read file as base64
function readFileAsBase64(file, callback) {
    const reader = new FileReader();
    reader.onload = (e) => callback(e.target.result);
    reader.readAsDataURL(file);
}

// Trigger exterior upload for specific slot
window.triggerExteriorUpload = function (index) {
    const brand = document.getElementById('carForm').brand.value;
    const model = document.getElementById('carForm').model.value;
    if (!brand || !model) {
        alert('⚠️ Por favor, introduce la Marca y el Modelo antes de subir imágenes.');
        return;
    }
    activeSlotIndex = index;
    document.getElementById('exteriorImageInput').click();
};

// Open editor for existing exterior image
window.openExteriorEditor = function (index) {
    const src = exteriorFiles[index];
    if (!src) {
        alert('No hay imagen para editar');
        return;
    }
    activeEditorType = 'exterior';
    activeSlotIndex = index;
    openEditorWithSrc(src);
};

// Open editor for existing interior image
window.openInteriorEditor = function (index) {
    const src = interiorFiles[index];
    if (!src) return;
    activeEditorType = 'interior';
    editingInteriorIndex = index;
    openEditorWithSrc(src);
};

// Open editor with a source
function openEditorWithSrc(src) {
    const editorModal = document.getElementById('editorModal');
    const editorImage = document.getElementById('editorImage');

    editorImage.crossOrigin = 'anonymous';
    editorImage.src = src;
    editorModal.style.display = 'flex';

    editorImage.onload = () => {
        if (cropper) cropper.destroy();
        cropper = new Cropper(editorImage, {
            viewMode: 2,
            responsive: true,
            background: false,
        });
    };
}

// Remove exterior image
window.removeExteriorImage = function (index) {
    exteriorFiles[index] = null;
    renderExteriorGallery();
};

// Render exterior gallery slots
function renderExteriorGallery() {
    const slots = document.querySelectorAll('#exteriorGalleryGrid .gallery-slot');
    slots.forEach((slot, index) => {
        const preview = slot.querySelector('.slot-preview');
        const guide = slot.querySelector('.slot-guide');
        const src = exteriorFiles[index];

        if (src) {
            preview.src = src;
            preview.style.display = 'block';
            slot.classList.add('has-image');
        } else {
            preview.src = '';
            preview.style.display = 'none';
            slot.classList.remove('has-image');
        }
    });
}

// Setup drag and drop for exterior slots
function setupExteriorDragDrop() {
    const grid = document.getElementById('exteriorGalleryGrid');
    if (!grid) return;

    const slots = grid.querySelectorAll('.gallery-slot');
    let draggedIndex = null;

    slots.forEach((slot, index) => {
        slot.setAttribute('draggable', 'true');

        slot.addEventListener('dragstart', (e) => {
            if (!exteriorFiles[index]) {
                e.preventDefault();
                return;
            }
            draggedIndex = index;
            slot.classList.add('dragging');
            e.dataTransfer.effectAllowed = 'move';
        });

        slot.addEventListener('dragend', () => {
            slot.classList.remove('dragging');
            draggedIndex = null;
        });

        slot.addEventListener('dragover', (e) => {
            e.preventDefault();
            if (draggedIndex !== null && draggedIndex !== index) {
                slot.classList.add('drag-over');
            }
        });

        slot.addEventListener('dragleave', () => {
            slot.classList.remove('drag-over');
        });

        slot.addEventListener('drop', (e) => {
            e.preventDefault();
            e.stopPropagation();
            slot.classList.remove('drag-over');

            if (draggedIndex !== null && draggedIndex !== index) {
                // Swap files
                const temp = exteriorFiles[draggedIndex];
                exteriorFiles[draggedIndex] = exteriorFiles[index];
                exteriorFiles[index] = temp;
                renderExteriorGallery();
            }
        });
    });
}

// Render interior gallery
function renderInteriorGallery() {
    const grid = document.getElementById('interiorGalleryGrid');
    if (!grid) return;
    grid.innerHTML = '';

    interiorFiles.forEach((src, index) => {
        const slot = document.createElement('div');
        slot.className = 'interior-slot';
        slot.setAttribute('draggable', 'true');
        slot.dataset.index = index;

        slot.innerHTML = `
            <img src="${src}" alt="Interior ${index + 1}">
            <div class="slot-actions" style="display:flex;">
                <div class="slot-edit" onclick="event.stopPropagation(); openInteriorEditor(${index})">✂</div>
                <div class="slot-remove" onclick="event.stopPropagation(); removeInteriorImage(${index})">×</div>
            </div>
        `;

        // Drag events
        slot.addEventListener('dragstart', (e) => {
            slot.classList.add('dragging');
            e.dataTransfer.setData('text/plain', index);
            e.dataTransfer.effectAllowed = 'move';
        });

        slot.addEventListener('dragend', () => {
            slot.classList.remove('dragging');
        });

        slot.addEventListener('dragover', (e) => {
            e.preventDefault();
            slot.classList.add('drag-over');
        });

        slot.addEventListener('dragleave', () => {
            slot.classList.remove('drag-over');
        });

        slot.addEventListener('drop', (e) => {
            e.preventDefault();
            slot.classList.remove('drag-over');
            const fromIndex = parseInt(e.dataTransfer.getData('text/plain'));
            const toIndex = index;
            if (fromIndex !== toIndex) {
                // Reorder array
                const [moved] = interiorFiles.splice(fromIndex, 1);
                interiorFiles.splice(toIndex, 0, moved);
                renderInteriorGallery();
            }
        });

        grid.appendChild(slot);
    });
}

// Remove interior image
window.removeInteriorImage = function (index) {
    interiorFiles.splice(index, 1);
    renderInteriorGallery();
};

function handleEditorOpen(file, type) {
    const brand = document.getElementById('carForm').brand.value;
    const model = document.getElementById('carForm').model.value;

    if (!brand || !model) {
        alert('⚠️ Por favor, introduce la Marca y el Modelo antes de subir imágenes.');
        return;
    }

    if (!file || !file.type.startsWith('image/')) return;

    activeEditorType = type;
    const reader = new FileReader();
    reader.onload = (e) => {
        const url = e.target.result;
        const editorModal = document.getElementById('editorModal');
        const editorImage = document.getElementById('editorImage');

        editorImage.src = url;
        editorModal.style.display = 'flex';

        if (cropper) cropper.destroy();

        cropper = new Cropper(editorImage, {
            viewMode: 2,
            responsive: true,
            background: false,
        });
    };
    reader.readAsDataURL(file);
}

window.closeEditor = function () {
    document.getElementById('editorModal').style.display = 'none';
    if (cropper) cropper.destroy();
    cropper = null;
    document.getElementById('editorImage').src = '';
    activeSlotIndex = null;
};

window.editorFlipX = function () {
    if (!cropper) return;
    const data = cropper.getData();
    cropper.scaleX(data.scaleX === -1 ? 1 : -1);
};

window.editorSave = function () {
    if (!cropper) return;

    const canvas = cropper.getCroppedCanvas({
        maxWidth: 1200,
        maxHeight: 1200,
    });

    const base64 = canvas.toDataURL('image/png');

    if (activeEditorType === 'exterior' && activeSlotIndex !== null) {
        exteriorFiles[activeSlotIndex] = base64;
        renderExteriorGallery();
    } else if (activeEditorType === 'interior') {
        // Check if editing existing or adding new
        if (editingInteriorIndex !== null) {
            interiorFiles[editingInteriorIndex] = base64;
            editingInteriorIndex = null;
        } else if (interiorFiles.length < 9) {
            interiorFiles.push(base64);
        }
        renderInteriorGallery();
    } else if (activeEditorType === 'main' || activeEditorType === 'logo') {
        const hiddenInputId = activeEditorType === 'main' ? 'finalImageSrc' : 'finalLogoSrc';
        const previewId = activeEditorType === 'main' ? 'mainPreview' : 'logoPreview';

        document.getElementById(hiddenInputId).value = base64;
        const p = document.getElementById(previewId);
        p.src = base64;
        p.classList.add('active');
    }

    closeEditor();
};

// Open editor from existing preview (Edit button)
// Open editor from existing preview (Edit button)
window.openEditorFromPreview = function (type) {
    console.log("openEditorFromPreview called with:", type);
    const hiddenInputId = type === 'main' ? 'finalImageSrc' : 'finalLogoSrc';
    const currentSrc = document.getElementById(hiddenInputId).value;

    console.log("Current Source:", currentSrc ? currentSrc.substring(0, 50) + "..." : "EMPTY");

    if (!currentSrc) {
        alert("No hay imagen seleccionada para editar.");
        return;
    }

    // Re-use logic: convert src to blob or just use url if it works
    // Cropper works with URLs so:
    activeEditorType = type;
    const editorModal = document.getElementById('editorModal');
    const editorImage = document.getElementById('editorImage');

    // IMPORTANT: Enable CORS for Firebase images to avoid tainted canvas
    editorImage.crossOrigin = "anonymous";

    editorImage.onload = () => {
        // Image loaded successfully, init cropper
        if (cropper) cropper.destroy();
        try {
            cropper = new Cropper(editorImage, {
                viewMode: 2,
                autoCropArea: 1,
                responsive: true,
                background: false,
                checkCrossOrigin: true,
            });
        } catch (err) {
            console.error("Cropper init failed:", err);
        }
    };

    editorImage.onerror = () => {
        console.warn("Posible error de CORS o carga de imagen. Si la imagen no carga, verifica la consola.");
        // We do not alert anymore as it might be a false positive if the user says it works.
        // closeEditor(); // Do not auto-close, let user decide
    };

    editorImage.src = currentSrc;
    editorModal.style.display = 'flex';

    // Remove synchronous Cropper init, wait for onload

};

function resetDropZones() {
    document.querySelectorAll('.drop-zone-preview').forEach(el => {
        el.src = '';
        el.classList.remove('active');
    });
    document.querySelectorAll('.drop-zone').forEach(el => el.classList.remove('dragover'));

    // Reset hidden input values
    const finalImageSrc = document.getElementById('finalImageSrc');
    const finalLogoSrc = document.getElementById('finalLogoSrc');
    if (finalImageSrc) finalImageSrc.value = '';
    if (finalLogoSrc) finalLogoSrc.value = '';

    // Reset exterior gallery slots
    document.querySelectorAll('#exteriorGalleryGrid .gallery-slot').forEach(slot => {
        slot.classList.remove('has-image');
        const preview = slot.querySelector('.slot-preview');
        if (preview) {
            preview.src = '';
            preview.style.display = 'none';
        }
    });

    // Reset interior gallery grid
    const interiorGrid = document.getElementById('interiorGalleryGrid');
    if (interiorGrid) interiorGrid.innerHTML = '';
}

// Create global wrapper for the inline onchange event in HTML
window.updatePreviewFromUrl = function (url, previewId, hiddenInputId) {
    if (!url) return;
    document.getElementById(hiddenInputId).value = url;
    const p = document.getElementById(previewId);
    p.src = url;
    p.classList.add('active');
};

