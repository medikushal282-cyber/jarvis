document.addEventListener('DOMContentLoaded', () => {
    let cart = [];

    const addToCartButtons = document.querySelectorAll('.add-to-cart');
    const cartList = document.getElementById('cart-items');
    const totalSpan = document.getElementById('total-amount');

    addToCartButtons.forEach(button => {
        button.addEventListener('click', () => {
            const productCard = button.closest('.product');
            const name = productCard.querySelector('h2').textContent;
            const price = parseFloat(productCard.querySelector('.price').textContent.replace('$', ''));
            
            const item = { name, price, quantity: 1 };
            const existingItem = cart.find(item => item.name === name);

            if (existingItem) {
                existingItem.quantity += 1;
            } else {
                cart.push(item);
            }

            updateCart();
        });
    });

    function updateCart() {
        cartList.innerHTML = '';
        let total =