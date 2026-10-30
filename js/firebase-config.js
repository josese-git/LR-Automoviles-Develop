import { initializeApp } from "https://www.gstatic.com/firebasejs/9.23.0/firebase-app.js";
import { getAnalytics } from "https://www.gstatic.com/firebasejs/9.23.0/firebase-analytics.js";
import { getFirestore } from "https://www.gstatic.com/firebasejs/9.23.0/firebase-firestore.js";
import { getStorage } from "https://www.gstatic.com/firebasejs/9.23.0/firebase-storage.js";
import { getAuth, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged } from "https://www.gstatic.com/firebasejs/9.23.0/firebase-auth.js";

const firebaseConfig = {
    apiKey: "AIzaSyBPbGmUp7pLvzosaW3ZN-XbogoR8HBXuZM",
    authDomain: "lrautomoviles.firebaseapp.com",
    projectId: "lrautomoviles",
    storageBucket: "lrautomoviles.firebasestorage.app",
    messagingSenderId: "391387461527",
    appId: "1:391387461527:web:82cd1a59b9de6a85f436d2",
    measurementId: "G-VZCCHNYVZ2"
};


const ADMIN_EMAIL = "julio@autosjveloce.com";


const app = initializeApp(firebaseConfig);
const analytics = getAnalytics(app);
const db = getFirestore(app);
const storage = getStorage(app);
const auth = getAuth(app);
const googleProvider = new GoogleAuthProvider();

export { db, storage, auth, googleProvider, ADMIN_EMAIL, signInWithPopup, signOut, onAuthStateChanged };
export { ref, uploadBytes, getDownloadURL } from "https://www.gstatic.com/firebasejs/9.23.0/firebase-storage.js";
