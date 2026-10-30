/**
 * Auth.js - Handles Login/Logout using SessionStorage
 */

const CREDENTIALS = {
    username: 'julio',
    password: 'padaleo' // In a real app, this would never be client-side :)
};

class Auth {
    constructor() {
        this.sessionName = 'jveloce_admin_session';
    }

    login(username, password) {
        if (username === CREDENTIALS.username && password === CREDENTIALS.password) {
            sessionStorage.setItem(this.sessionName, 'true');
            return true;
        }
        return false;
    }

    logout() {
        sessionStorage.removeItem(this.sessionName);
        window.location.href = '../index.html';
    }

    isAuthenticated() {
        return sessionStorage.getItem(this.sessionName) === 'true';
    }

    requireAuth() {
        if (!this.isAuthenticated()) {
            window.location.href = '../login.html';
        }
    }
}

const auth = new Auth();
window.auth = auth;
