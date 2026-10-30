import { db } from './firebase-config.js';
import { INITIAL_CARS } from './initial-cars.js';
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
const DEFAULT_CARS = INITIAL_CARS;

class Store {
    constructor() {
        this.subscribers = [];
        this.currentCars = [...DEFAULT_CARS];
        this.init();
    }

    init() {
        try {
            const colRef = collection(db, COLLECTION_NAME);
            const q = query(colRef, orderBy('order', 'asc'));

            onSnapshot(q, (snapshot) => {
                const cars = [];
                snapshot.forEach((doc) => {
                    cars.push({ id: doc.id, ...doc.data() });
                });
                
                if (cars.length > 0) {
                    this.notifySubscribers(cars);
                } else {
                    // Show initial cars
                    this.notifySubscribers(DEFAULT_CARS);
                    // Try seeding if Firestore is ready and not seeded
                    if (!localStorage.getItem('seeded_lr_v1')) {
                        this.seedDefaults();
                    }
                }
            }, (error) => {
                console.warn("Firestore snapshot error (using initial cars):", error);
                this.notifySubscribers(DEFAULT_CARS);
            });
        } catch (error) {
            console.warn("Firestore init error (using initial cars):", error);
            this.notifySubscribers(DEFAULT_CARS);
        }
    }

    async seedDefaults() {
        try {
            console.log('Seeding initial 10 cars to Firestore...');
            for (const car of DEFAULT_CARS) {
                await this.addCar(car);
            }
            localStorage.setItem('seeded_lr_v1', 'true');
            console.log('Initial cars seeded successfully.');
        } catch (e) {
            console.warn('Could not seed defaults to Firestore yet:', e);
        }
    }

    subscribe(callback) {
        this.subscribers.push(callback);
        if (this.currentCars && this.currentCars.length > 0) {
            callback(this.currentCars);
        }
    }

    notifySubscribers(cars) {
        this.currentCars = cars;
        this.subscribers.forEach(cb => cb(cars));
    }

    async addCar(car) {
        if (!car.id) {
            car.id = `${car.brand}-${car.model}-${car.year}`.toLowerCase().replace(/\s+/g, '-');
        }
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
        const batch = writeBatch(db);
        cars.forEach((car, index) => {
            const docRef = doc(db, COLLECTION_NAME, car.id);
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

const store = new Store();
window.store = store;

export default store;