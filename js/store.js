import { db } from './firebase-config.js';
import {
    collection,
    onSnapshot,
    setDoc,
    deleteDoc,
    doc,
    updateDoc,
    query,
    orderBy,
    writeBatch
} from "https://www.gstatic.com/firebasejs/9.23.0/firebase-firestore.js";

const COLLECTION_NAME = 'anuncios';
const DEFAULT_CARS = [
    {
        id: 'mercedes-class-a-2019',
        brand: 'Mercedes',
        model: 'Clase A 200d',
        year: '2019',
        fuel: 'Diesel',
        transmission: 'Auto',
        image: 'assets/mercedes_a_class.png',
        logo: 'assets/logo_mercedes.png',
        sold: false,
        price: '28.500€',
        order: 0
    },
    {
        id: 'peugeot-3008-2016',
        brand: 'Peugeot',
        model: '3008',
        year: '2016',
        fuel: 'Diesel',
        transmission: 'Manual',
        image: 'assets/peugeot_3008.png',
        logo: 'assets/logo_peugeot.png',
        sold: false,
        price: '18.900€',
        order: 1
    },
    {
        id: 'kia-sportage-2020',
        brand: 'Kia',
        model: 'Sportage',
        year: '2020',
        fuel: 'Híbrido',
        transmission: 'Auto',
        image: 'assets/kia_sportage.png',
        logo: 'assets/logo_kia_white.png',
        logoClass: 'wide', // Special handling for wide logos
        sold: false,
        price: '24.200€',
        order: 2
    }
];

class Store {
    constructor() {
        this.subscribers = [];
        this.init();
    }

    init() {
        // Set up real-time listener with correct sorting
        const colRef = collection(db, COLLECTION_NAME);
        const q = query(colRef, orderBy('order', 'asc'));

        onSnapshot(q, (snapshot) => {
            const cars = [];
            snapshot.forEach((doc) => {
                cars.push({ id: doc.id, ...doc.data() });
            });
            this.notifySubscribers(cars);

            // Optional: Seed default data if empty (only once)
            // This logic is a bit risky in production but good for migration
            if (cars.length === 0 && !localStorage.getItem('seeded_v1')) {
                this.seedDefaults();
            }
        });
    }

    async seedDefaults() {
        console.log('Seeding default data to Firestore...');
        for (const car of DEFAULT_CARS) {
            await this.addCar(car);
        }
        localStorage.setItem('seeded_v1', 'true');
    }

    subscribe(callback) {
        this.subscribers.push(callback);
    }

    notifySubscribers(cars) {
        this.subscribers.forEach(cb => cb(cars));
    }

    async addCar(car) {
        // Use ID if provided (from migration/defaults) or generate one
        if (!car.id) {
            car.id = `${car.brand}-${car.model}-${car.year}`.toLowerCase().replace(/\s+/g, '-');
        }

        // Assign a default order if not present (sort of naive, but works for basic app)
        if (typeof car.order !== 'number') {
            car.order = Date.now();
        }

        try {
            await setDoc(doc(db, COLLECTION_NAME, car.id), car);
            console.log("Document successfully written!", car.id);
        } catch (error) {
            console.error("Error writing document: ", error);
            throw error;
        }
    }

    async deleteCar(id) {
        try {
            await deleteDoc(doc(db, COLLECTION_NAME, id));
            console.log("Document successfully deleted!", id);
        } catch (error) {
            console.error("Error removing document: ", error);
            throw error;
        }
    }

    async updateCar(id, updatedData) {
        try {
            const docRef = doc(db, COLLECTION_NAME, id);
            await updateDoc(docRef, updatedData);
            console.log("Document successfully updated!", id);
        } catch (error) {
            console.error("Error updating document: ", error);
            throw error;
        }
    }

    async reorderCars(cars) {
        // 'cars' is the array in the desired order
        const batch = writeBatch(db);

        cars.forEach((car, index) => {
            const docRef = doc(db, COLLECTION_NAME, car.id);
            // Only update if order changed to save writes? 
            // For simplicity, just update all order fields.
            batch.update(docRef, { order: index });
        });

        try {
            await batch.commit();
            console.log("Batch reorder committed");
        } catch (error) {
            console.error("Error reordering:", error);
            throw error;
        }
    }
}

// Export singleton
const store = new Store();
// Expose to window for backward compatibility/easy access if needed, 
// though with modules it's better to import.
window.store = store;

export default store;

