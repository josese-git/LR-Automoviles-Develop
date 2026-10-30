const { initializeApp } = require("firebase/app");
const { getFirestore, collection, getDocs, doc, setDoc, limit, query } = require("firebase/firestore");

const jveloceConfig = {
    apiKey: "AIzaSyAKr2_t_-JjzeiO8G8vQUkitqgDXi49ih0",
    authDomain: "jveloce-cf602.firebaseapp.com",
    projectId: "jveloce-cf602",
    storageBucket: "jveloce-cf602.firebasestorage.app",
    messagingSenderId: "779415799900",
    appId: "1:779415799900:web:759f5e87559312550dfe99"
};

const lrConfig = {
  apiKey: "AIzaSyBPbGmUp7pLvzosaW3ZN-XbogoR8HBXuZM",
  authDomain: "lrautomoviles.firebaseapp.com",
  projectId: "lrautomoviles",
  storageBucket: "lrautomoviles.firebasestorage.app",
  messagingSenderId: "391387461527",
  appId: "1:391387461527:web:82cd1a59b9de6a85f436d2"
};

const appJ = initializeApp(jveloceConfig, "jveloce");
const dbJ = getFirestore(appJ);

const appLR = initializeApp(lrConfig, "lr");
const dbLR = getFirestore(appLR);

async function copyCars() {
    try {
        console.log("Fetching first 10 cars from JVeloce...");
        const q = query(collection(dbJ, "anuncios"), limit(10));
        const snap = await getDocs(q);
        console.log(`Found ${snap.size} cars.`);

        for (const document of snap.docs) {
            const data = document.data();
            console.log(`Copying ${document.id} (${data.brand} ${data.model})...`);
            await setDoc(doc(dbLR, "anuncios", document.id), data);
            console.log(`-> Copied ${document.id} successfully!`);
        }
        console.log("All 10 cars successfully copied to LR Automoviles!");
    } catch (e) {
        console.error("Error copying cars:", e);
    }
}
copyCars();